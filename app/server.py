# FederPDF - lokaler PDF-Server
# Läuft auf 127.0.0.1, wird vom WebView2-Wrapper (FederPDF.exe) gestartet.
import os
import re
import sys
import io
import json
import uuid
import base64
import shutil

import pymupdf
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Body
from fastapi.responses import HTMLResponse, Response, FileResponse
if getattr(sys, "frozen", False):
    # Als PyInstaller-EXE: Dateien neben der EXE, gebündelte Assets in _MEIPASS
    BASE = os.path.dirname(sys.executable)
    STATIC = os.path.join(getattr(sys, "_MEIPASS", BASE), "static")
else:
    # Quellcode-Ausführung: Projektwurzel ist eine Ebene über app/
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    STATIC = os.path.join(BASE, "app", "static")

UPLOADS = os.path.join(BASE, "uploads")
SIGN_DIR = os.path.join(BASE, "signatures")
TESSDATA = os.path.join(BASE, "tessdata")   # deu/eng Sprachdaten fuer Tesseract (PyMuPDF-OCR)
DEMO = os.path.join(BASE, "demo", "demo.pdf")
# Einstellungen NEBEN dem Programmordner: Deployment = FederPDF\einstellungen.json
# (ueberlebt server-Aktualisierungen); Entwicklung = Projektwurzel
PREFS_FILE = os.path.join(os.path.dirname(BASE) if getattr(sys, "frozen", False) else BASE,
                          "einstellungen.json")
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(SIGN_DIR, exist_ok=True)

app = FastAPI(title="FederPDF")

APP_VERSION = "0.21.27"   # wird im Über-Dialog (Klick auf Logo/FederPDF) angezeigt


@app.middleware("http")
async def _kein_cache(request, call_next):
    """Lokaler Server: niemals cachen - sonst laeuft die UI nach Updates auf alten Stand."""
    resp = await call_next(request)
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


docs = {}     # doc_id -> {"path": str, "doc": pymupdf.Document}
current = {}  # zuletzt geöffnetes Dokument (für Doppelklick-Start)
undo_stacks = {}  # did -> Liste von Undo-Einträgen
sig_unlocked = {}  # fname -> entschlüsselte PNG-Bytes (nur im RAM, bis Serverstop)

# ---------- Passwort-geschützte Signaturen (.pwdsig, Fernet/PBKDF2) ----------

def _fernet_schluessel(passwort: str, salt: bytes):
    """Ableitung: PBKDF2-HMAC-SHA256, 200k Iterationen."""
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    return base64.urlsafe_b64encode(kdf.derive(passwort.encode("utf-8")))


def _sig_verschluesseln(png_bytes: bytes, passwort: str) -> str:
    import base64
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    tok = Fernet(_fernet_schluessel(passwort, salt)).encrypt(png_bytes)
    return json.dumps({"v": 1, "salt": base64.b64encode(salt).decode(),
                       "token": tok.decode()})


def _sig_entschluesseln(inhalt: str, passwort: str) -> bytes:
    import base64
    from cryptography.fernet import Fernet, InvalidToken
    daten = json.loads(inhalt)
    salt = base64.b64decode(daten["salt"])
    try:
        return Fernet(_fernet_schluessel(passwort, salt)).decrypt(daten["token"].encode())
    except InvalidToken:
        raise HTTPException(401, "Falsches Passwort")


def _sig_gesperrt(fname: str) -> bool:
    return fname.lower().endswith(".pwdsig")


def _sig_bytes(fname: str):
    """PNG-Bytes einer Signatur; None, wenn geschützt und noch nicht entsperrt."""
    fname = os.path.basename(fname)
    pfad = os.path.join(SIGN_DIR, fname)
    if not os.path.isfile(pfad):
        return None
    if _sig_gesperrt(fname):
        return sig_unlocked.get(fname)
    with open(pfad, "rb") as f:
        return f.read()


def push_undo(did, entry):
    st = undo_stacks.setdefault(did, [])
    st.append(entry)
    if len(st) > 60:
        st.pop(0)


def _txt_props(did_page_annot_nm, fallback_rect=None):
    """Liest Text-Eigenschaften aus einem PDFW-TXT-NM-Marker. Farb-Falle
    (v0.21.11): Hinter der Farbe stehen noch spacing/leading
    ("...:r,g,b:spacing:leading") - deshalb maxsplit=5; das Farbfeld (3. Feld,
    Kommaliste ohne Doppelpunkt) bleibt so sauber. Frueher maxsplit=3 liess das
    Nachfolgefeld in die Farbe rutschen -> float() starb -> still Schwarz."""
    nm = did_page_annot_nm or ""
    font, size, color = "helv", 11.0, [0, 0, 0]
    if nm.startswith("PDFW-TXT:"):
        try:
            teile = nm.split(":", 5)
            if len(teile) >= 4:
                font = teile[1] or font
                size = float(teile[2])
                color = [float(v) for v in teile[3].split(",")]
        except Exception:
            pass
    return font, size, color


def _txt_farbe01(farbe):
    """Marker-Farbliste als geklemmtes 0-1-Tupel. Der Marker traegt 0-1-Werte
    (die UI schickt Hex/255); nur die TEXTPAGE liefert 0-255. Werte > 1
    (fremde Eintraege) gelten als 0-255-Skala - niemals blind /255 rechnen
    (zweite Schwarz-Falle bis v0.21.10)."""
    werte = [float(c) for c in (list(farbe) + [0, 0, 0])[:3]]
    if max(werte) > 1.0:
        werte = [c / 255 for c in werte]
    return tuple(max(0.0, min(1.0, c)) for c in werte)


def _ap_farbe(doc, xref):
    """Erste rg-Farbangabe aus dem Normal-AP der Annotation (0-1-Tripel) oder None."""
    try:
        typ, wert = doc.xref_get_key(xref, "AP/N")
        if typ != "xref":
            return None
        m = re.search(rb"([0-9.]+) ([0-9.]+) ([0-9.]+) rg", doc.xref_stream(int(wert.split()[0])) or b"")
        return tuple(float(v) for v in m.groups()) if m else None
    except Exception:
        return None


def _txt_ap_auffrischen(doc):
    """Bestandsdateien heilen (v0.21.11): Bis v0.21.10 geriet die Farbe von
    Freitexten im Appearance-Stream auf Schwarz (Farbfeld des PDFW-TXT-Markers
    wurde nicht mehr geparst bzw. durch 255 geteilt). Der Marker selbst traegt
    die richtige Farbe - APs, deren rg-Wert davon abweicht, beim Oeffnen neu
    bauen. Frisch angelegte APs passen exakt und bleiben unangetastet."""
    for pg_i in range(doc.page_count):
        pg = doc[pg_i]
        for a in list(pg.annots() or []):
            if a.type[1] != "FreeText":
                continue
            nm = a.info.get("id", "") or ""
            if not nm.startswith("PDFW-TXT:"):
                continue
            soll = _txt_farbe01(_txt_props(nm)[2])
            ist = _ap_farbe(doc, a.xref)
            if ist is None:
                continue
            if max(abs(ist[i] - soll[i]) for i in range(3)) > 0.01:
                _freetext_ap_mit_abstand(doc, a, pg.rect.height,
                                         _txt_spacing(nm), _txt_leading(nm))


def _doc(did: str) -> pymupdf.Document:
    if did not in docs:
        raise HTTPException(404, "Dokument nicht (mehr) geoeffnet")
    return docs[did]["doc"]


def _open(path: str) -> dict:
    path = os.path.normpath(path)
    if not os.path.isfile(path):
        raise HTTPException(404, "Datei nicht gefunden: " + path)
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise HTTPException(400, "Kann PDF nicht oeffnen: " + str(e))
    _txt_ap_auffrischen(doc)   # alte Dateien mit schwarz geratenen Text-APs heilen
    did = uuid.uuid4().hex[:12]
    docs[did] = {"path": path, "doc": doc}
    current.clear()
    current.update({
        "id": did,
        "name": os.path.basename(path),
        "pages": doc.page_count,
        "toc": doc.get_toc(simple=True),
    })
    return dict(current)


def _ensure_demo():
    if os.path.isfile(DEMO):
        return
    os.makedirs(os.path.dirname(DEMO), exist_ok=True)
    doc = pymupdf.open()
    toc = []
    p = doc.new_page()
    p.insert_text((72, 90), "FederPDF Demo-Dokument", fontsize=18)
    p.insert_text((72, 120), "Seite 1: Markiere mich - diese Zeile ist zum Kopieren da.", fontsize=11)
    p.insert_text((72, 140), "Klicke auf eine Zeile, um sie in die Zwischenablage zu legen.", fontsize=11)
    toc.append([1, "Einleitung", 1])
    p = doc.new_page()
    p.insert_text((72, 90), "Kapitel 1: Lesezeichen", fontsize=16)
    for i in range(20):
        p.insert_text((72, 120 + i * 16), f"Beispieltext Zeile {i+1} auf Seite 2.", fontsize=11)
    toc.append([1, "Kapitel 1 - Lesezeichen", 2])
    toc.append([2, "Unterabschnitt", 2])
    p = doc.new_page()
    p.insert_text((72, 90), "Kapitel 2: Formular", fontsize=16)
    p.insert_text((72, 130), "Vorname:", fontsize=11)
    p.insert_text((72, 170), "Nachname:", fontsize=11)
    p.insert_text((72, 210), "Lieblingsfarbe:", fontsize=11)
    for name, y in (("Vorname", 130), ("Nachname", 170), ("Lieblingsfarbe", 210)):
        w = pymupdf.Widget()
        w.rect = pymupdf.Rect(160, y - 12, 380, y + 8)
        w.field_name = name
        w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        w.border_width = 0.5
        p.add_widget(w)
    toc.append([1, "Kapitel 2 - Formular", 3])
    doc.set_toc(toc)
    doc.save(DEMO)
    doc.close()


@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(STATIC, "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/favicon.ico")
def favicon():
    path = os.path.join(STATIC, "logo.png")
    if not os.path.isfile(path):
        raise HTTPException(404)
    return Response(content=open(path, "rb").read(), media_type="image/png")


@app.get("/logo.png")
def logo():
    """Logo in Originalgroesse fuer den Über-Dialog (Klick auf Logo/FederPDF)."""
    path = os.path.join(STATIC, "logo.png")
    if not os.path.isfile(path):
        raise HTTPException(404)
    return Response(content=open(path, "rb").read(), media_type="image/png")


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/version")
def version():
    """Eckdaten für den Über-Dialog (Klick auf Logo/FederPDF in der Kopfzeile)."""
    return {"name": "FederPDF", "version": APP_VERSION,
            "pymupdf": pymupdf.__version__, "lokal": True}


@app.get("/api/prefs")
def get_prefs():
    """Gespeicherte UI-Einstellungen (portunabhaengig, da der Serverport pro Start wechselt)."""
    try:
        with open(PREFS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@app.post("/api/prefs")
async def set_prefs(data: dict = Body(...)):
    if len(data) > 40:
        raise HTTPException(400, "Zu viele Eintraege")
    try:
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, "Einstellungen nicht speicherbar: " + str(e))


@app.get("/api/current")
def current_doc():
    return dict(current) if current else {}


@app.get("/api/demo")
def demo():
    _ensure_demo()
    return _open(DEMO)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    did_prefix = uuid.uuid4().hex[:8]
    name = os.path.basename(file.filename or "dokument.pdf")
    path = os.path.join(UPLOADS, did_prefix + "_" + name)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return _open(path)


@app.get("/api/open")
def open_by_path(q: str):
    return _open(q)


@app.get("/api/page/{did}/{n}")
def page(did: str, n: int, dpi: int = 110):
    d = _doc(did)
    if n < 0 or n >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    pix = d[n].get_pixmap(dpi=dpi, annots=False)
    return Response(content=pix.tobytes("png"), media_type="image/png")


@app.get("/api/text/{did}/{n}")
def text(did: str, n: int):
    d = _doc(did)
    words = d[n].get_text("words")
    lines = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)
    out = []
    for key in sorted(lines):
        ws = sorted(lines[key], key=lambda w: w[0])
        out.append({
            "x0": min(w[0] for w in ws),
            "y0": min(w[1] for w in ws),
            "x1": max(w[2] for w in ws),
            "y1": max(w[3] for w in ws),
            "t": " ".join(w[4] for w in ws),
            "b": key[0],
        })
    # Zeilen NEU gruppieren: zusammengehörig ist, wer im selben PDF-Block steht
    # ODER auf derselben Zeile liegt (y-Überlappung). Grund: ersetzte Zeilen
    # (text/replace) sind neu eingesetzte Textobjekte mit eigener Blocknummer -
    # optisch gehören sie weiterhin zu ihrer Tabellenzeile (Datum | Text | Betrag).
    anz = len(out)
    elter = list(range(anz))

    def finde(i):
        while elter[i] != i:
            elter[i] = elter[elter[i]]
            i = elter[i]
        return i

    for i in range(anz):
        ri = out[i]
        for j in range(i + 1, anz):
            rj = out[j]
            if ri["b"] == rj["b"]:
                elter[finde(i)] = finde(j)
                continue
            ueberlapp = min(ri["y1"], rj["y1"]) - max(ri["y0"], rj["y0"])
            minh = min(ri["y1"] - ri["y0"], rj["y1"] - rj["y0"])
            if minh > 0 and ueberlapp > 0.4 * minh:
                elter[finde(i)] = finde(j)
    gruppen = {}
    for i in range(anz):
        gruppen.setdefault(finde(i), []).append(i)
    for neue_nummer, (_, mitglieder) in enumerate(sorted(gruppen.items())):
        for i in mitglieder:
            out[i]["b"] = neue_nummer
    return {"page_w": d[n].rect.width, "page_h": d[n].rect.height, "lines": out}


@app.get("/api/fields/{did}")
def fields(did: str):
    d = _doc(did)
    out = []
    for pno, pg in enumerate(d):
        for w in pg.widgets():
            out.append({
                "page": pno,
                "name": w.field_name,
                "type": w.field_type_string,
                "value": "" if w.field_value is None else str(w.field_value),
                "rect": list(w.rect),
            })
    return out


def _feld_wert_setzen(doc, w, value):
    """Setzt Widget-Wert; Leerstring braucht /V-Diretcing (PyMuPDF ignoriert '')."""
    if value == "":
        w.field_value = " "
        w.update()
        doc.xref_set_key(w.xref, "V", "()")
    else:
        w.field_value = value
        w.update()


@app.post("/api/field/{did}")
async def set_field(did: str, page: int = Form(...), name: str = Form(...), value: str = Form(...)):
    d = _doc(did)
    found = False
    for w in d[page].widgets():
        if w.field_name == name:
            old = "" if w.field_value is None else str(w.field_value)
            if w.field_type_string in ("CheckBox", "RadioButton"):
                w.field_value = value.lower() in ("1", "true", "yes", "an", "x")
                w.update()
            else:
                _feld_wert_setzen(d, w, value)
            found = True
            push_undo(did, {"op": "field", "page": page, "name": name, "value": old})
    if not found:
        raise HTTPException(404, "Feld nicht gefunden: " + name)
    return {"ok": True}


@app.get("/api/hasannots/{did}")
def hasannots(did: str):
    """Gibt es bewegliche Objekte (Signaturen/Texte/Formen/Markierungen)? -
    fuer die Einbrennen-Rueckfrage."""
    d = _doc(did)
    for pg in d:
        for a in pg.annots():
            if a.type[1] in ("Stamp", "FreeText", "Square", "Circle", "Line", "Ink",
                             "Highlight", "Underline", "StrikeOut", "Squiggly"):
                return {"any": True}
    return {"any": False}


def _bild_geister(pg, erwartet: int):
    """Ordinalnummern (Reihenfolge get_image_info) von Bildplatzierungen, die von
    einem SPAETER gezeichneten, deckungsweissen Rechteck voll ueberdeckt werden.
    image-move/-rotate ueberdecken die alte Stelle weiss und setzen das Bild neu
    ein - die alte Platzierung bleibt unsichtbar in der Datei (Bild-Geist) und
    war bislang weiter waehlbar; ihr Verschieben erzeugte eine sichtbare Kopie.
    Markerlose Erkennung: get_bboxlog liefert Bilder und Pfade in Content-Stream-
    Reihenfolge (fill-image/fill-path), get_drawings die Farbe (Deckkraft 1,
    SEIT v0.21.13 in beliebiger Deckfarbe - Deckel folgen der gemessenen
    Hintergrundfarbe; Vorbehalt: exotische Mischmodi wie Multiply meldet
    get_drawings nicht, ein solcher Deckel liesse das Bild durchscheinen und
    wuerde hier zu Unrecht gefiltert - praktisch rar). ImageMask-Bilder
    (1-bit-Faxmasken, Briefkoepfe!) meldet get_bboxlog als "fill-imgmask" -
    sie zaehlen mit, sonst divergiert die Zaehlung gegen get_image_info und
    das Sicherheitsnetz schaltete den Filter fuer solche Dokumente KOMPLETT
    ab (Nutzer-Fund v0.21.12, ING-Briefkopf mit gestapelten ING-/Loewen-
    Masken: Geist blieb greifbar, jeder Zug kopierte). Reihenfolge der
    gemischten Liste == get_image_info (empirisch geprueft)."""
    try:
        log = pg.get_bboxlog()
        zeichnungen = pg.get_drawings()
    except Exception:
        return set()
    log_bilder = [(i, e[1]) for i, e in enumerate(log)
                  if e[0] in ("fill-image", "fill-imgmask")]
    if len(log_bilder) != erwartet:   # Zaehlung divergiert: lieber gar nicht filtern
        return set()
    deckel = set()
    for dr in zeichnungen:
        if dr.get("type") == "f" and dr.get("fill_opacity", 1) >= 0.999 and dr.get("fill"):
            r = dr["rect"]
            deckel.add((r.x0, r.y0, r.x1, r.y1))
    if not deckel:
        return set()
    pfade = []
    for i, e in enumerate(log):
        if e[0] != "fill-path":
            continue
        b = e[1]
        for (x0, y0, x1, y1) in deckel:
            if (abs(b[0] - x0) < 0.5 and abs(b[1] - y0) < 0.5
                    and abs(b[2] - x1) < 0.5 and abs(b[3] - y1) < 0.5):
                pfade.append((i, b))
                break
    geister = set()
    for nr, (bidx, bbox) in enumerate(log_bilder):
        for pidx, pb in pfade:
            if pidx <= bidx:
                continue   # nur WEISS-Kaestchen zaehlen, die NACH dem Bild liegen
            if (pb[0] - 1 <= bbox[0] and bbox[2] <= pb[2] + 1
                    and pb[1] - 1 <= bbox[1] and bbox[3] <= pb[3] + 1):
                geister.add(nr)
                break
    return geister


def _tinten_box(d, inf):
    """Enge Huelle der GEMALTEN Pixel einer Bildplatzierung, Seiten-Koordinaten
    in pt - oder None (= volle Platzierungsbox). Grundlage der Tintenrahmen
    (v0.21.19): Briefkopf-Masken sind Vollflaechen, deren sichtbare Tinte nur
    15-20 % bedeckt ('ING'-Zug links, Loewe rechts). Gemessen wird die Maske
    (ImageMask) bzw. die SMask (Alpha); ohne Transparenz ist alles Tinte.
    SEIT v0.21.20 auch bei GEDREHTEN Platzierungen: die Pixel-Ecken werden
    durch die Platzierungs-Matrix (inf['transform'], MuPDF-Konvention TOP-DOWN)
    auf die Seite gerechnet und die achsenparallele Huelle davon genommen -
    der Rahmen ist dann die Huelle der gedrehten Kontur (etwas groesser als
    die Kontur selbst, aber deutlich enger als die Vollflaeche; vorher lief
    die Messung nur achsenparallel und der Rahmen sprang beim Drehen auf die
    Vollflaeche)."""
    xref = inf.get("xref", 0)
    if xref <= 0:
        return None
    try:
        quelle = xref
        obj = d.xref_object(xref, compressed=True)
        if "/ImageMask" not in obj.replace(" ", ""):
            smask = d.extract_image(xref).get("smask", 0)
            if not smask:
                return None                    # voll deckendes Bild: Tinte == Platzierung
            quelle = smask
        pix = pymupdf.Pixmap(d, quelle)
        from PIL import Image
        # Graustufen-Kanal zeilenweise ziehen - Pixmap-STRIDE kann Zeilen
        # auffuellen (CCITT-Masken!), frombytes wuerde dann still werfen
        w, h, n, stride = pix.width, pix.height, pix.n, pix.stride
        s = pix.samples
        if n == 1 and stride == w:
            kanal = s
        else:
            kanal = bytearray(w * h)
            for y in range(h):
                base = y * stride
                if n == 1:
                    kanal[y * w:(y + 1) * w] = s[base:base + w]
                else:
                    for x in range(w):
                        kanal[y * w + x] = s[base + x * n]
        im = Image.frombytes("L", (w, h), bytes(kanal))
        bb = im.getbbox()
        if not bb:
            return None
        # Pixelecken -> Einheitsquadr -> Platzierungs-Matrix -> Seite. MuPDFs
        # inf['transform'] ist TOP-DOWN (f = Oberkante) und v zaehlt wie die
        # Pixelzeilen von OBEN - keine Hoehen-Spiegelung noetig (Falle: die
        # Stream-cm selbst ist y-up, transform nicht!).
        a, b, c, dd, e, f = inf.get("transform", (1, 0, 0, 1, 0, 0))
        us = (bb[0] / w, bb[2] / w)
        vs = (bb[1] / h, bb[3] / h)
        ecken = [(a * u + c * v + e, b * u + dd * v + f) for u in us for v in vs]
        xs = [p[0] for p in ecken]
        ys = [p[1] for p in ecken]
        ix0, iy0, ix1, iy1 = min(xs), min(ys), max(xs), max(ys)
        box = inf["bbox"]
        if (ix1 - ix0) * (iy1 - iy0) > 0.95 * (box[2] - box[0]) * (box[3] - box[1]):
            return None                        # fast volle Flaeche: keine Verengung wert
        return [ix0, iy0, ix1, iy1]
    except Exception:
        return None


@app.get("/api/imageinfo/{did}/{page}")
def image_info(did: str, page: int):
    """Eingebettete Bilder der Seite mit Platzierungsrechteck und xref; 'ink'
    ist die enge Tinten-Box (Anzeige/Klick in der UI - die Operationen rechnen
    weiter mit der Platzierungsbox). Ganzseitenbilder (Scans) und Inline-
    Bilder werden nicht gemeldet."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    pg = d[page]
    pw, ph = pg.rect.width, pg.rect.height
    infos = pg.get_image_info(xrefs=True)
    geister = _bild_geister(pg, len(infos)) if infos else set()
    bilder = []
    for nr, inf in enumerate(infos):
        if inf.get("xref", 0) <= 0:
            continue                                   # Inline-Bild: nicht per xref verschiebbar
        b = inf["bbox"]
        if (b[2] - b[0]) * (b[3] - b[1]) > 0.9 * pw * ph:
            continue                                   # Ganzseitenbild (Scan): nicht verschiebbar
        if nr in geister:
            continue                                   # unsichtbarer Bild-Geist (weiss ueberdeckt)
        eintrag = {"bbox": [round(v, 1) for v in b], "xref": inf["xref"]}
        try:
            # Gesamtwinkel der Platzierung (x-Achsen-Spalte der top-down-
            # transform, Uhrzeigersinn positiv): die Dreh-VORSCHAU braucht ihn
            # als ?rot= fuer das vorgedrehte Bitmap (v0.21.23) - die Huelle
            # eines gedrehten Objekts ist kein Bildmass, das Bitmap auf
            # Huellenmass zu strecken verzerrt (Nutzer-Fund: "zweite Drehung
            # immer verzerrter").
            from math import atan2, degrees
            a_t, b_t = inf["transform"][:2]
            eintrag["winkel"] = round(degrees(atan2(b_t, a_t)), 1)
        except Exception:
            pass
        ink = _tinten_box(d, inf)
        if ink:
            eintrag["ink"] = [round(v, 1) for v in ink]
        bilder.append(eintrag)
    return {"page_w": pw, "bilder": bilder}


def _weissdeckel(r: pymupdf.Rect) -> pymupdf.Rect:
    """Weissdeckel 1pt ueberstehen lassen: exakt passend bleibt die gerasterte
    Bildkante der alten Platzierung als duenner farbiger Rest sichtbar
    (Antialiasing zeichnet sie hauchfein um die Weissflaeche herum)."""
    return pymupdf.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1)


_CSTROM_TOKEN = re.compile(
    rb"\((?:\\.|[^\\()])*\)"      # Literal-String ueberspringen
    rb"|<[0-9A-Fa-f\s]*>"         # Hex-String ueberspringen
    rb"|<<|>>"
    rb"|/[^\s/\[\]<>(){}]+"
    rb"|[^\s/\[\]<>(){}<>/]+")


def _mat_mult(m, n):
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2,
            c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def _farbe_zu_rgb(farbe):
    """Getrackte Fuellfarbe -> (r,g,b) 0-1, oder None."""
    if not farbe:
        return None
    typ, k = farbe
    try:
        if typ == "rgb":
            return tuple(k)
        if typ == "grau":
            return (k[0],) * 3
        if typ == "cmyk":
            c, m, y, s = k
            return ((1 - c) * (1 - s), (1 - m) * (1 - s), (1 - y) * (1 - s))
        if typ == "sc":
            if len(k) == 1:
                return (k[0],) * 3
            if len(k) == 3:
                return tuple(k)
            if len(k) == 4:
                c, m, y, s = k
                return ((1 - c) * (1 - s), (1 - m) * (1 - s), (1 - y) * (1 - s))
    except Exception:
        return None
    return None


def _bild_namen(d, pg, xref: int):
    """Alle Ressourcen-Namen, unter denen das Bild xref auf der Seite gemalt
    wird (auch die fzImgN-Namen frisch eingesetzter Kopien)."""
    namen = {name for name, fxref in _xobj_map(d, pg.xref).items() if fxref == xref}
    if not namen:
        for e in pg.get_images(full=True):
            if e[0] == xref:
                namen.add(e[7])
    return namen


_CHIRURGIE_MALER = {b"Tj", b"TJ", b"'", b'"', b"Do", b"sh", b"EI",
                    b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}


def _bild_platzierung(d, pg, xref: int, ziel_r: pymupdf.Rect):
    """Die Platzierung von Bild xref, deren Kasten zu ziel_r passt - mit allem,
    was die Chirurgie (v0.21.15) braucht: Paint-Farbe, aufrufendem Ressourcen-
    Namen, Content-Stream-xref und den BYTE-GRENZEN des innersten q..Q-Blocks
    (nur loeschbar, wenn der Block AUSSER unserem Do keine malenden Operatoren
    enthaelt - sonst chirugiere wir nicht, sondern fallen auf den Deckel-Pfad
    zurueck). None, wenn nicht auffindbar. Beispiel ING-Briefkopf:
    '... rg  q 1 0 0 1 55.2 787.8 cm ... /MA2 Do  Q' - der rg steht AUSSERHALB,
    der Block ist sauber isolierbar."""
    try:
        ziel_namen = _bild_namen(d, pg, xref)
        if not ziel_namen:
            return None
        seite = _xobj_map(d, pg.xref)
        if not seite:
            seite = {e[7]: e[0] for e in pg.get_images(full=True)}
        hoehe = pg.rect.height
        fund = []

        def scanne(stream: bytes, sxref, res_map: dict, zustand, tiefe: int):
            if tiefe > 4:
                return
            toks = list(_CSTROM_TOKEN.finditer(stream))
            operanden, letzter_name = [], b""
            stapel = []          # je q: {"ctm", "farbe", "start", "ops": [tok...]}
            i = 0
            while i < len(toks):
                m = toks[i]
                tok = m.group(0)
                if tok == b"BI":                  # Inline-Bild: alles bis EI skippen
                    while i < len(toks) and toks[i].group(0) != b"EI":
                        i += 1
                    i += 1
                    continue
                if tok == b"q":
                    stapel.append({"ctm": zustand["ctm"], "farbe": zustand["farbe"],
                                   "start": m.start(), "ops": []})
                    operanden.clear()
                elif tok == b"Q":
                    if stapel:
                        rahmen = stapel.pop()
                        if rahmen.get("ziel"):
                            fund.append({"farbe": rahmen["farbe"],
                                         "name": rahmen["ziel"],
                                         "bbox": rahmen["bbox"],
                                         "ctm": rahmen["ctm"],
                                         "stream": sxref,
                                         "start": rahmen["start"], "ende": m.end(),
                                         "sauber": rahmen["ops"] == [b"Do"]})
                    operanden.clear()
                elif tok == b"cm" and len(operanden) >= 6 and stapel:
                    rahmen = stapel[-1]
                    rahmen["ctm"] = _mat_mult(tuple(operanden[-6:]), rahmen["ctm"])
                    operanden.clear()
                elif tok == b"rg" and len(operanden) >= 3:
                    zustand["farbe"] = ("rgb", tuple(operanden[-3:]))
                    if stapel:
                        stapel[-1]["farbe"] = zustand["farbe"]
                    operanden.clear()
                elif tok == b"g" and operanden:
                    zustand["farbe"] = ("grau", (operanden[-1],))
                    if stapel:
                        stapel[-1]["farbe"] = zustand["farbe"]
                    operanden.clear()
                elif tok == b"k" and len(operanden) >= 4:
                    zustand["farbe"] = ("cmyk", tuple(operanden[-4:]))
                    if stapel:
                        stapel[-1]["farbe"] = zustand["farbe"]
                    operanden.clear()
                elif tok in (b"sc", b"scn") and operanden:
                    zustand["farbe"] = ("sc", tuple(operanden))
                    if stapel:
                        stapel[-1]["farbe"] = zustand["farbe"]
                    operanden.clear()
                elif tok == b"Do":
                    name = letzter_name[1:].decode("latin-1", "replace")
                    operanden.clear()
                    if stapel:
                        stapel[-1]["ops"].append(b"Do")
                    if name in ziel_namen and stapel:
                        a, b, c, dd, e, f = stapel[-1]["ctm"]
                        xs = (e, a + e, c + e, a + c + e)
                        ys = (f, b + f, dd + f, b + dd + f)
                        box = pymupdf.Rect(min(xs), hoehe - max(ys), max(xs), hoehe - min(ys))
                        stapel[-1]["ziel"] = name
                        stapel[-1]["bbox"] = box
                    elif name not in ziel_namen:
                        fxref = res_map.get(name)
                        if fxref:
                            try:
                                if "/Subtype/Form" in d.xref_object(fxref, compressed=True):
                                    scanne(d.xref_stream(fxref), None, _xobj_map(d, fxref),
                                           {"ctm": stapel[-1]["ctm"] if stapel else zustand["ctm"],
                                            "farbe": stapel[-1]["farbe"] if stapel else zustand["farbe"]},
                                           tiefe + 1)
                            except Exception:
                                pass
                elif tok in _CHIRURGIE_MALER:
                    if stapel:
                        stapel[-1]["ops"].append(tok)
                    operanden.clear()
                elif tok.startswith(b"/"):
                    letzter_name = tok
                else:
                    try:
                        operanden.append(float(tok))
                    except ValueError:
                        operanden.clear()
                i += 1

        for sxref in pg.get_contents():
            scanne(d.xref_stream(sxref), sxref, seite, {"ctm": (1, 0, 0, 1, 0, 0), "farbe": None}, 0)
        if not fund:
            return None
        for f in fund:
            box = f["bbox"]
            if (abs(box.x0 - ziel_r.x0) < 2 and abs(box.y0 - ziel_r.y0) < 2
                    and abs(box.x1 - ziel_r.x1) < 2 and abs(box.y1 - ziel_r.y1) < 2):
                return f
        return None
    except Exception:
        return None


def _platzierung_farben(d, pg, xref: int, ziel_r: pymupdf.Rect):
    """Fuellfarbe (r,g,b 0-1) der Platzierung ziel_r - duenner Wrapper ueber
    _bild_platzierung (v0.21.13: Maskenfarben; v0.21.15: liefert auch die
    Blockgrenzen fuer die Chirurgie)."""
    pl = _bild_platzierung(d, pg, xref, ziel_r)
    return pl["farbe"] if pl else None


def _xobj_map(d, besitzer_xref: int):
    """Ressourcen-XObject-Namen -> xref fuer Seite oder Form-XObject."""
    art, wert = d.xref_get_key(besitzer_xref, "Resources/XObject")
    if art == "xref":
        try:
            wert = d.xref_object(int(str(wert).split()[0]), compressed=True)
            art = "dict"
        except Exception:
            wert = None
    aus = {}
    if art == "dict" and wert:
        for m in re.finditer(r"/(\S+?) (\d+) 0 R", str(wert)):
            aus[m.group(1)] = int(m.group(2))
    return aus


def _deckelfarbe(pg, r: pymupdf.Rect):
    """Hintergrundfarbe um Rect r messen (Ring ~6pt aus dem gerasterten Papier,
    Annotationen ausgenommen). Liefert (rgb 0-1 | None, gleichmaessig).
    gleichmaessig=False heisst: Foto-/Verlaufs-/Gemischhintergrund - JEDE
    Deckelfarbe liesse einen sichtbaren Fleck zurueck, der Aufrufer verweigert
    den Zug dann besser."""
    try:
        ring = pymupdf.Rect(r.x0 - 6, r.y0 - 6, r.x1 + 6, r.y1 + 6) & pg.rect
        if ring.is_empty or ring.width < 3 or ring.height < 3:
            return None, False
        pix = pg.get_pixmap(clip=ring, annots=False)
        w, h, n = pix.width, pix.height, pix.n
        sx, sy = ring.width / w, ring.height / h
        punkte = []
        for y in range(h):
            py = ring.y0 + (y + 0.5) * sy
            for x in range(w):
                px = ring.x0 + (x + 0.5) * sx
                if r.x0 - 0.5 <= px <= r.x1 + 0.5 and r.y0 - 0.5 <= py <= r.y1 + 0.5:
                    continue                       # Objektflaeche selbst: ausklammern
                i = (y * w + x) * n
                punkte.append((pix.samples[i], pix.samples[i + 1], pix.samples[i + 2]))
        if len(punkte) < 30:
            return None, False
        med = tuple(sorted(p[k] for p in punkte)[len(punkte) // 2] for k in range(3))
        gut = sum(1 for p in punkte
                  if abs(p[0] - med[0]) <= 24 and abs(p[1] - med[1]) <= 24 and abs(p[2] - med[2]) <= 24)
        if gut / len(punkte) < 0.97:
            return None, False
        return tuple(v / 255 for v in med), True
    except Exception:
        return None, False


def _bild_einsetzen(d, pg, rect: pymupdf.Rect, xref: int, farbe):
    """Bild per xref einsetzen und - bei ImageMask-Platzierungen - die
    Paint-Farbe in den frischen Insert-Stream schreiben (insert_image kennt
    keine Fuellfarbe, ohne sie werden Masken schwarz). Der Wrap in ein eigenes
    q...Q bleibt gnadenlos balanciert, egal wie der Stream aussieht."""
    pg.insert_image(rect, xref=xref)
    if not farbe:
        return
    try:
        inhalte = pg.get_contents()
        if not inhalte:
            return
        daten = d.xref_stream(inhalte[-1])
        if b"Do" not in daten:
            return                                 # nicht unser frischer Insert-Stream
        zusatz = b"q\n%.4f %.4f %.4f rg\n" % tuple(farbe)
        d.update_stream(inhalte[-1], zusatz + daten + b"\nQ\n")
    except Exception:
        pass                                       # ohne Farbe = bisheriges Verhalten


def _cm_anker(matrix, ziel_r: pymupdf.Rect, hoehe: float):
    """cm-Matrix so verschieben, dass die bemalte Einheitsquadr-Huelle exakt
    auf ziel_r landet (Ecken numerisch, top-down -> PDF-y)."""
    a, b, c, dd, e, f = matrix
    xs = (e, a + e, c + e, a + c + e)
    ys = (f, b + f, dd + f, b + dd + f)
    return (a, b, c, dd, e + ziel_r.x0 - min(xs), f + (hoehe - ziel_r.y1) - min(ys))


def _cm_dreh_matrix(w: float, h: float, rot: float, neu_r: pymupdf.Rect, hoehe: float):
    """cm-Matrix: Bild (w x h) um rot Grad (Uhrzeigersinn auf dem Schirm) drehen
    und in die Huelle neu_r legen (Ankerung ueber _cm_anker - je nach Winkel
    bildet eine andere Ecke den Huellenrand)."""
    from math import sin, cos, radians
    r = radians(rot)
    c_, s_ = cos(r), sin(r)
    return _cm_anker((w * c_, -w * s_, h * s_, h * c_, 0.0, 0.0), neu_r, hoehe)


def _chirurgie_block(name: str, farbe, matrix) -> bytes:
    """Ein selbstenthaltenene q..Q-Block, der das Bild per Ressourcen-Namen an
    der Matrix-Position malt (inkl. Masken-Fuellfarbe)."""
    rgb = b""
    if farbe:
        rgb = b"%.4f %.4f %.4f rg\n" % tuple(farbe)
    a, b, c, dd, e, f = matrix
    return (b"q\n" + rgb
            + b"%.4f %.4f %.4f %.4f %.4f %.4f cm\n" % (a, b, c, dd, e, f)
            + b"/" + name.encode("latin-1", "replace") + b" Do Q\n")


def _bild_chirurgie(d, pg, plaetze, matrix_fn):
    """Echte Objekt-Chirurgie (v0.21.15, PDFgear-Paritaet): die alten Platz-
    ierungs-Bloecke werden aus den Content-Streams HERAUSGESCHNITTEN (kein
    Deckel, kein Geist, Text unterm Bild bleibt unversehrt) und als frische
    Bloecke an den LETZTEN Content-Stream angehaengt. matrix_fn(platz, hoehe)
    liefert die Ziel-cm-Matrix (verschieben/strecken oder drehen). True bei
    Erfolg; None, wenn ein Block nicht sauber isolierbar ist (dann ruft der
    Aufrufer den Deckel-Fallback). Das Undo ist SELBST eine Chirurgie
    (Platzierung an der Zielstelle selbst finden und invers zurueckschieben) -
    keine Byte-Positionen merken, verkettete Undos bleiben robust."""
    try:
        if not plaetze or not all(p.get("sauber") for p in plaetze):
            return None
        inhalte = pg.get_contents()
        if not inhalte:
            return None
        letzte = inhalte[-1]
        daten = {sx: d.xref_stream(sx) for sx in {p["stream"] for p in plaetze} | {letzte}}
        hoehe = pg.rect.height
        # Bloecke aus ihren Streams loeschen - absteigend je Stream, damit die
        # Offsets der weiteren Bloecke im selben Stream gueltig bleiben
        for sx in sorted({p["stream"] for p in plaetze}):
            gruppe = sorted([p for p in plaetze if p["stream"] == sx],
                            key=lambda p: p["start"], reverse=True)
            strom = daten[sx]
            for p in gruppe:
                strom = strom[:p["start"]] + strom[p["ende"]:]
            daten[sx] = strom
        # Anhaenge (Ebenen-Reihenfolge) an den letzten Stream
        anhaenge = [_chirurgie_block(p["name"], _farbe_zu_rgb(p["farbe"]),
                                     matrix_fn(p, hoehe)) for p in plaetze]
        daten[letzte] = daten[letzte] + b"\n" + b"".join(anhaenge)
        for sx, strom in daten.items():
            d.update_stream(sx, strom)
        return True
    except Exception:
        return None


@app.post("/api/image/move/{did}")
async def image_move(did: str, page: int = Form(...), xref: int = Form(0),
                     xrefs: str = Form(""), alt: str = Form(...), neu: str = Form(...)):
    """Bild verschieben: alte Platzierung weiss ueberdecken, Bild an der neuen
    Stelle wieder einsetzen (gleiche eingebettete Grafik per xref, kein Re-Embedding).
    xrefs (JSON-Liste) verschiebt MEHRERE uebereinanderliegende Ebenen in einem
    Zug (Briefkopflogos bestehen oft aus gestapelten Masken: "ING" + Loewe) -
    ein Deckel, Einfuegen in Ebenen-Reihenfolge, EIN Undo-Eintrag."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    try:
        xr = [int(v) for v in json.loads(xrefs)] if xrefs else []
    except Exception:
        raise HTTPException(400, "xrefs ist keine Liste")
    if not xr:
        xr = [xref]
    if not xr or any(v <= 0 for v in xr):
        raise HTTPException(400, "Dieses Bild ist nicht verschiebbar")
    alt_r = pymupdf.Rect(*[float(v) for v in json.loads(alt)])
    neu_r = pymupdf.Rect(*[float(v) for v in json.loads(neu)])
    pg = d[page]
    # Chirurgie-Pfad (v0.21.15): Platzierung wirklich verschieben - kein Deckel,
    # kein Geist, Hintergrund/Text unter der alten Stelle bleibt unversehrt
    # (PDFgear-Paritaet, Nutzer-Fund). Die LINEARE Transformation der Platzierung
    # bleibt erhalten (v0.21.16: gedrehte Objekte behalten beim Ziehen ihren
    # Winkel - vorher wurde axis-aligned neu gesetzt: Drehung weg + verzerrt):
    # Skalierung im BILDRAUM vorschalten (mat_mult(S, M)), Translation ueber
    # den Huellen-Anker (_cm_anker).
    plaetze = [_bild_platzierung(d, pg, v, alt_r) for v in xr]
    if all(plaetze):
        hoehe = pg.rect.height
        s_x = (neu_r.width / alt_r.width) if alt_r.width > 0.01 else 1.0
        s_y = (neu_r.height / alt_r.height) if alt_r.height > 0.01 else 1.0

        def _move_fn(p, h, _sx=s_x, _sy=s_y):
            a, b, c, dd, e, f = p["ctm"]
            return _cm_anker(_mat_mult((_sx, 0, 0, _sy, 0, 0), (a, b, c, dd, e, f)),
                             neu_r, h)
        if _bild_chirurgie(d, pg, plaetze, _move_fn):
            push_undo(did, {"op": "image-move", "page": page, "xref": xr[0], "xrefs": xr,
                            "alt": list(alt_r), "neu": list(neu_r),
                            "matrizen": [list(p["ctm"]) for p in plaetze]})
            return {"ok": True}
    # Fallback: alte Stelle deckeln (nur bei nicht isolierbaren Platzierungen)
    deckel_r = _weissdeckel(alt_r)
    deckelfarbe, gleichmaessig = _deckelfarbe(pg, deckel_r)
    if not gleichmaessig:
        raise HTTPException(400, "Hintergrund ist hier nicht einfarbig - "
                                 "das Bild lie\u00dfe sich nur mit sichtbarem Fleck verschieben")
    pg.draw_rect(deckel_r, color=None, fill=deckelfarbe or (1, 1, 1), overlay=True)
    for v in xr:
        _bild_einsetzen(d, pg, neu_r, v, _platzierung_farben(d, pg, v, alt_r))
    push_undo(did, {"op": "image-move", "page": page, "xref": xr[0], "xrefs": xr,
                    "alt": list(alt_r), "neu": list(neu_r)})
    return {"ok": True}


def _bild_bytes_vom_xref(d, xref: int) -> bytes:
    """Eingebettetes Bild als RGBA-PNG ziehen. SMask (Transparenz) kombiniert
    (PyMuPDF-FaQ-Rezept Pixmap(basis, maske)), exotische Formate (CMYK, J2K)
    via Pixmap -> PNG. Fuer Live-Vorschau und Drehen."""
    info = d.extract_image(xref)
    if info.get("smask", 0) > 0:
        try:
            basis = pymupdf.Pixmap(d, xref)
            if not basis.alpha:
                basis = pymupdf.Pixmap(basis, pymupdf.Pixmap(d, info["smask"]))
            if basis.colorspace and basis.colorspace.n > 3:
                basis = pymupdf.Pixmap(pymupdf.csRGB, basis)
            return basis.tobytes("png")
        except Exception:
            pass   # unten der PIL-/Pixmap-Fallback
    from PIL import Image
    try:
        with Image.open(io.BytesIO(info["image"])) as im:
            im.load()
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            return buf.getvalue()
    except Exception:
        pix = pymupdf.Pixmap(d, xref)
        if pix.colorspace and pix.colorspace.n > 3:
            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
        return pix.tobytes("png")


def _masken_png(d, xref: int, farbe):
    """ImageMask als RGBA-PNG in ihrer Paint-Farbe (unbemalt transparent).
    Masken haben KEINE eigene Farbe - sie werden in der Fuellfarbe der
    Platzierung gemalt. Das rohe Bitmap (1-bit, s/w) in die Vorschau zu
    strecken zeigt einen schwarzen/weissen Kasten (Nutzer-Fund v0.21.22:
    'Rahmen fuellt sich beim Drehen schwarz'). farbe = rgb 0-1 (aus
    _farbe_zu_rgb) oder None -> Schwarz. Konvention wie _tinten_box:
    Pixmap 255 = gemalt; Kanal zeilenweise (STRIDE padet, CCITT!)."""
    from PIL import Image
    pix = pymupdf.Pixmap(d, xref)
    w, h, n, stride = pix.width, pix.height, pix.n, pix.stride
    s = pix.samples
    if n == 1 and stride == w:
        kanal = s
    else:
        kanal = bytearray(w * h)
        for y in range(h):
            base = y * stride
            if n == 1:
                kanal[y * w:(y + 1) * w] = s[base:base + w]
            else:
                for x in range(w):
                    kanal[y * w + x] = s[base + x * n]
    grau = Image.frombytes("L", (w, h), bytes(kanal))
    rgb = farbe if farbe else (0.0, 0.0, 0.0)
    flaeche = Image.new("RGB", (w, h), tuple(int(round(c * 255)) for c in rgb))
    aus = flaeche.convert("RGBA")
    aus.putalpha(grau.point(lambda v: 255 if v > 127 else 0).convert("L"))
    buf = io.BytesIO()
    aus.save(buf, format="PNG")
    return buf.getvalue()


def _png_drehen(png: bytes, grad: float) -> bytes:
    """RGBA-PNG als vorgedrehte Vorschau: Uhrzeigersinn positiv, Canvas auf
    die gedrehte Huelle erweitert (expand) - das Seitenverhaeltnis der Huelle
    passt dann zur Platzierungs-Huelle, die Vorschau kann es unverzerrt
    auf _pdfRect-Mass malen (v0.21.23, Muster der Signatur-Vorschau ?rot=)."""
    from PIL import Image
    with Image.open(io.BytesIO(png)) as im:
        im.load()
        gedreht = im.convert("RGBA").rotate(-grad, expand=True, resample=Image.BICUBIC)
    buf = io.BytesIO()
    gedreht.save(buf, format="PNG")
    return buf.getvalue()


@app.get("/api/image/file/{did}/{page}/{xref}")
def image_file(did: str, page: int, xref: int, rot: float = 0):
    """Bildbytes eines eingebetteten Bildes (fuer die Live-Vorschau beim
    Skalieren/Drehen im Client). ImageMask-xrefs werden in ihrer PLACEMENT-
    Paint-Farbe geliefert (v0.21.22) - sonst waere die Dreh-Vorschau s/w.
    rot (v0.21.23) dreht das Vorschau-Bitmap vor (Canvas = gedrehte Huelle):
    der Client schickt den Gesamtwinkel aus /api/imageinfo, damit die zweite
    Drehung eines schon gedrehten Objekts die Tinte nicht auf Huellenmass
    streckt."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    if xref <= 0:
        raise HTTPException(400, "Dieses Bild ist nicht abrufbar")
    try:
        if "/ImageMask" in d.xref_object(xref, compressed=True).replace(" ", ""):
            pg = d[page]
            farbe = None
            for inf in pg.get_image_info(xrefs=True):
                if inf.get("xref") == xref:
                    farbe = _farbe_zu_rgb(_platzierung_farben(d, pg, xref,
                                                              pymupdf.Rect(inf["bbox"])))
                    break
            png = _masken_png(d, xref, farbe)
        else:
            png = _bild_bytes_vom_xref(d, xref)
        if rot:
            png = _png_drehen(png, float(rot) % 360.0)
    except Exception:
        raise HTTPException(404, "Bild konnte nicht extrahiert werden")
    return Response(content=png, media_type="image/png")


@app.post("/api/image/rotate/{did}")
async def image_rotate(did: str, page: int = Form(...), xref: int = Form(0),
                       xrefs: str = Form(""), alt: str = Form(...), winkel: float = Form(...),
                       mitte: str = Form("")):
    """Eingebettetes Bild um DELTA-Grad weiterdrehen (Uhrzeigersinn positiv).
    Eingebettete Bilder tragen keine Rotations-Metadaten (anders als Signatur-
    NM-Marker) - daher wird das Delta mit der JETZTigen Platzierung komponiert
    (v0.21.17). 'mitte' (PDF-Punkt, die UI schickt die Tintenrahmen-Mitte) ist
    der FIXPUNKT der Drehung - was dort liegt, bleibt liegen (v0.21.21; vorher
    wurde die Huelle um die Mitte ZENTRIERT, was bei unmittiger Tinte das
    Objekt verschob). Ohne 'mitte' dreht das Bild um seine Huellenmitte.
    xrefs (JSON-Liste) dreht gestapelte Ebenen GEMEINSAM."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    try:
        xr = [int(v) for v in json.loads(xrefs)] if xrefs else []
    except Exception:
        raise HTTPException(400, "xrefs ist keine Liste")
    if not xr:
        xr = [xref]
    if not xr or any(v <= 0 for v in xr):
        raise HTTPException(400, "Dieses Bild ist nicht drehbar")
    alt_r = pymupdf.Rect(*[float(v) for v in json.loads(alt)])
    rot = float(winkel) % 360.0
    from math import sin, cos, radians
    rad = radians(rot)
    rc, rs_ = cos(rad), sin(rad)
    hw, hh = _bbox_gedreht(alt_r.width, alt_r.height, rot)
    cx, cy = (alt_r.x0 + alt_r.x1) / 2, (alt_r.y0 + alt_r.y1) / 2
    try:                                    # optionale Drehmitte (v0.21.19: Tintenrahmen-Mitte,
        if mitte:                           # damit Vorschau und Commit um denselben Punkt drehen)
            m = json.loads(mitte)
            cx, cy = float(m[0]), float(m[1])
    except Exception:
        pass
    pg = d[page]   # Seitenreferenz einmal ziehen und wiederverwenden
    # Chirurgie-Pfad (v0.21.15): Drehen als cm-Matrix auf dem ORIGINAL-Bitmap
    # (keine Rasterung, keine Qualitaetsverluste, kein Deckel, kein Geist).
    # v0.21.17: Das Delta wird mit der BESTEHENDEN Platzierung KOMPONIERT -
    # die Huellbox eines schon gedrehten Objekts ist kein Bildmass! (Nutzer-
    # Fund: erneutes Drehen verzerrte.) Bildmasse/Winkel leben in der Matrix.
    # v0.21.21: Drehung um 'mitte' ist ein FIXPUNKT (t = C - R*C nachschalten),
    # NICHT eine um C zentrierte Huelle - das ist nur bei mittiger Tinte
    # dasselbe, sonst verschiebt das Drehen das Objekt um den Abstand
    # Tintenmitte<->Platzierungsmitte (Nutzer-Fund: "Drehen verschiebt
    # zusaetzlich"; die CSS-Vorschau dreht um die Rahmenmitte des div).
    r_mat = (rc, -rs_, rs_, rc, 0.0, 0.0)

    def _fixpunkt_dreh(m):
        """R(delta) NACH der Platzierung komponieren, dann um (cx, cy) als
        Fixpunkt verschieben. Achtung Koordinaten: mitte kommt top-down aus
        der UI, die Matrix lebt im y-up Rohstrom-Raum (wie _cm_anker)."""
        a2, b2, c2, d2, e2, f2 = _mat_mult(m, r_mat)
        mx, my = cx, pg.rect.height - cy
        return (a2, b2, c2, d2,
                e2 + mx - (rc * mx + rs_ * my),
                f2 + my - (-rs_ * mx + rc * my))

    def _cm_huelle(m, hoehe):
        """Achsenparallele Huelle der bemalten Einheitsquadr-Ecken als PDF-Rect."""
        a2, b2, c2, d2, e2, f2 = m
        xs = (e2, a2 + e2, c2 + e2, a2 + c2 + e2)
        ys = (f2, b2 + f2, d2 + f2, b2 + d2 + f2)
        return pymupdf.Rect(min(xs), hoehe - max(ys), max(xs), hoehe - min(ys))

    plaetze = [_bild_platzierung(d, pg, v, alt_r) for v in xr]
    if all(plaetze):
        hoehe = pg.rect.height
        _rot_fn = lambda p, h: _fixpunkt_dreh(tuple(p["ctm"]))
        # Ziel-Rect einmalig aus der ersten Ebene bestimmen (Stack teilt die Geometrie)
        neu_r = _cm_huelle(_fixpunkt_dreh(tuple(plaetze[0]["ctm"])), hoehe)
        if _bild_chirurgie(d, pg, plaetze, _rot_fn):
            push_undo(did, {"op": "image-rotate", "page": page, "xref": xr[0], "xrefs": xr,
                            "alt": list(alt_r), "neu": list(neu_r), "winkel": winkel,
                            "matrizen": [list(p["ctm"]) for p in plaetze]})
            return {"ok": True, "rect": [round(v, 1) for v in neu_r]}
    # Fallback: Bitmap drehen + alte Stelle deckeln (nur bei unsauberen Bloecken)
    from PIL import Image
    # Ziel-Huelle = alte Huelle um (cx, cy) GEDREHT (Fixpunkt, nicht um C
    # zentriert - gleiche Geometrie wie der Chirurgie-Pfad darueber)
    hx, hy = (alt_r.x0 + alt_r.x1) / 2, (alt_r.y0 + alt_r.y1) / 2
    ncx = cx + rc * (hx - cx) - rs_ * (hy - cy)
    ncy = cy + rs_ * (hx - cx) + rc * (hy - cy)
    neu_r = pymupdf.Rect(ncx - hw / 2, ncy - hh / 2, ncx + hw / 2, ncy + hh / 2)
    gedrehte_pngs = []
    for v in xr:
        png = _bild_bytes_vom_xref(d, v)
        with Image.open(io.BytesIO(png)) as im:
            gedreht = im.rotate(-rot, expand=True, resample=Image.BICUBIC)
        buf = io.BytesIO()
        gedreht.save(buf, format="PNG")
        gedrehte_pngs.append(buf.getvalue())
    deckel_r = _weissdeckel(alt_r)
    deckelfarbe, gleichmaessig = _deckelfarbe(pg, deckel_r)
    if not gleichmaessig:
        raise HTTPException(400, "Hintergrund ist hier nicht einfarbig - "
                                 "das Bild lie\u00dfe sich nur mit sichtbarem Fleck drehen")
    pg.draw_rect(deckel_r, color=None, fill=deckelfarbe or (1, 1, 1), overlay=True)
    for p in gedrehte_pngs:
        pg.insert_image(neu_r, stream=p)
    push_undo(did, {"op": "image-rotate", "page": page, "xref": xr[0], "xrefs": xr,
                    "alt": list(alt_r), "neu": list(neu_r)})
    return {"ok": True, "rect": [round(v, 1) for v in neu_r]}


@app.post("/api/save/{did}")
def save(did: str, flatten: int = 0):
    d = _doc(did)
    seiten = []
    if flatten:
        # Gespacete Freitexte ZUERST zeichenweise als Seiteninhalt einsetzen
        # (PyMuPDF-bake wuerde den Zeichenabstand verlieren), dann wegredigieren.
        for pg_i in range(d.page_count):
            pg = d[pg_i]
            for a in list(pg.annots() or []):
                if a.type[1] != "FreeText":
                    continue
                nm = a.info.get("id", "") or ""
                sp = _txt_spacing(nm)
                if not sp:
                    continue
                font, size, color = _txt_props(nm)
                col01 = _txt_farbe01(color)   # Farb-Falle v0.21.11 (frueher /255 -> Schwarz)
                r = a.rect
                text = (a.info.get("content") or "").replace("\r\n", "\n")
                if font.startswith("doc~"):
                    # Eingebettete Dokument-Schrift: auf DIESER Seite registrieren,
                    # Vorschub aus den echten Font-Metriken (get_text_length kennt
                    # nur Base14). Zeichnen dann wie gehabt zeichenweise mit Tc.
                    res = _docfont_aufloesen(d, font)
                    if res is None:
                        continue   # AP hat Helv-Fallback -> normales bake uebernimmt
                    fx, fontobj, fbuf = res
                    alias = f"PWb{fx}"
                    try:
                        pg.insert_font(fontname=alias, fontbuffer=fbuf)
                    except Exception:
                        pass
                    for i, zeile in enumerate(text.split("\n")):
                        x = r.x0 + 2
                        y = r.y0 + 2.5 + size * 0.2 + i * size * 1.25
                        for ch in zeile:
                            if ch != " ":
                                pg.insert_text((x, y), ch, fontsize=size, fontname=alias, color=col01)
                            x += fontobj.text_length(ch, fontsize=size) + sp
                    pg.delete_annot(a)
                    continue
                for i, zeile in enumerate(text.split("\n")):
                    x = r.x0 + 2
                    y = r.y0 + 2.5 + size * 0.2 + i * size * 1.25
                    for ch in zeile:
                        if ch != " ":
                            pg.insert_text((x, y), ch, fontsize=size, fontname=font, color=col01)
                        x += pymupdf.get_text_length(ch, fontname=font, fontsize=size) + sp
                pg.delete_annot(a)
        # Signaturen/Rest-Texte einbrennen: werden Seiteninhalt, nicht mehr entfernbar.
        # widgets=False: Formularfelder bleiben ausfuellbar. Danach ist Undo sinnlos.
        seiten = [i for i in range(d.page_count) if d[i].annots()]   # UI laedt diese Seitenbilder neu
        d.bake(widgets=False)
        undo_stacks[did] = []
    path = docs[did]["path"]
    try:
        d.saveIncr()
    except Exception:
        tmp = path + ".tmp"
        d.save(tmp, garbage=3, deflate=True)
        d.close()
        shutil.move(tmp, path)
        docs[did]["doc"] = pymupdf.open(path)
    return {"ok": True, "path": path, "flattened": bool(flatten), "seiten": seiten}


@app.get("/api/saveas/{did}")
def saveas(did: str, path: str, flatten: int = 0):
    """Dokument unter neuem Namen speichern - die neue Datei wird zum Arbeitsdokument
    (wie ueblich bei "Speichern unter"). Ohne garbage: Xref-Nummern bleiben stabil,
    Undo-Referenzen ueberleben. Original-Datei bleibt unveraendert liegen.
    flatten=1 brennt Signaturen/Texte vorher ein (wie beim normalen Speichern)."""
    d = _doc(did)
    path = os.path.normpath(path)
    if path.lower() == os.path.normpath(docs[did]["path"]).lower():
        raise HTTPException(400, "Ziel ist die bereits geöffnete Datei – bitte 'Speichern' nutzen")
    try:
        if flatten:
            d.bake(widgets=False)
            undo_stacks[did] = []
        d.save(path, deflate=True)
        d.close()
        docs[did]["doc"] = pymupdf.open(path)
        docs[did]["path"] = path
        if current.get("id") == did:
            current["name"] = os.path.basename(path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, "Speichern unter fehlgeschlagen: " + str(e))
    return {"ok": True, "path": path, "flattened": bool(flatten)}


@app.get("/api/download/{did}")
def download(did: str):
    d = _doc(did)
    path = docs[did]["path"]
    buf = io.BytesIO()
    d.save(buf, garbage=3, deflate=True)
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'},
    )


# ---------- Signaturen ----------

def _entferne_weissen_hintergrund(img, schwellwert: int = 232):
    """Macht Pixel oberhalb des Schwellwerts transparent (wie PDFgears Signatur-Trick). Im RAM."""
    from PIL import Image
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r > schwellwert and g > schwellwert and b > schwellwert and a > 0:
                px[x, y] = (r, g, b, 0)
    return img


@app.get("/api/signatures")
def signatures():
    out = []
    for fn in sorted(os.listdir(SIGN_DIR)):
        locked = _sig_gesperrt(fn)
        if fn.lower().endswith((".png", ".jpg", ".jpeg")) or locked:
            out.append({"file": fn, "name": os.path.splitext(fn)[0],
                        "locked": locked, "unlocked": locked and fn in sig_unlocked})
    return out


def _alle_stamp_verweise_umbenennen(old: str, new: str):
    """NM-Marker aller gesetzten Signatur-Annotationen auf neuen Dateinamen ziehen.
    Rot-Suffix (':90' etc.) bleibt erhalten; Dateinamen enthalten nie ':' (Windows)."""
    praefix = f"PDFW-SIG:{old}"
    for did in list(docs.keys()):
        d = docs[did]["doc"]
        for pno in range(d.page_count):
            for a in d[pno].annots():
                if a.type[1] == "Stamp":
                    nm = a.info.get("id", "") or ""
                    if nm.startswith(praefix):
                        rest = nm[len(praefix):]      # '' oder ':rot'
                        if new:
                            d.xref_set_key(a.xref, "NM", f"(PDFW-SIG:{new}{rest})")
                        else:                          # Loeschen: Verweis leeren
                            d.xref_set_key(a.xref, "NM", "(PDFW-SIG:)")


@app.post("/api/signature/rename")
async def signature_rename(old: str = Form(...), new: str = Form(...)):
    old = os.path.basename(old)
    new = "".join(c for c in new if c not in '\\/:*?"<>|').strip()
    if not new:
        raise HTTPException(400, "Name ist leer")
    src = os.path.join(SIGN_DIR, old)
    if not os.path.isfile(src):
        raise HTTPException(404, "Signatur nicht gefunden")
    ext = os.path.splitext(old)[1] or ".png"
    dst = os.path.join(SIGN_DIR, new + ext)
    if os.path.isfile(dst):
        raise HTTPException(400, "Dieser Name existiert bereits")
    os.rename(src, dst)
    if old in sig_unlocked:
        sig_unlocked[new + ext] = sig_unlocked.pop(old)
    _alle_stamp_verweise_umbenennen(old, new + ext)
    return {"ok": True, "file": new + ext}


@app.post("/api/signature/delete")
async def signature_delete(fname: str = Form(...)):
    fname = os.path.basename(fname)
    path = os.path.join(SIGN_DIR, fname)
    if os.path.isfile(path):
        os.remove(path)
    sig_unlocked.pop(fname, None)
    # Verweise leeren -> Vorschau zeigt Platzhalter; gespeicherte PDFs bleiben unberuehrt
    _alle_stamp_verweise_umbenennen(fname, "")
    return {"ok": True}


@app.get("/api/signature/file/{fname}")
def signature_file(fname: str, rot: float = 0):
    fname = os.path.basename(fname)
    path = os.path.join(SIGN_DIR, fname)
    if not os.path.isfile(path):
        raise HTTPException(404, "Signatur nicht gefunden")
    daten = None
    if _sig_gesperrt(fname):
        if fname not in sig_unlocked:
            raise HTTPException(401, "Signatur ist passwortgeschützt – erst entsperren")
        daten = sig_unlocked[fname]
    else:
        with open(path, "rb") as f:
            daten = f.read()
    if rot % 360:
        from PIL import Image
        import io as _io
        with Image.open(_io.BytesIO(daten)) as im:
            gedreht = im.convert("RGBA").rotate(-(rot % 360), expand=True,
                                                resample=Image.BICUBIC)
        buf = _io.BytesIO()
        gedreht.save(buf, format="PNG")
        daten = buf.getvalue()
    return Response(content=daten, media_type="image/png")


@app.post("/api/signature/unlock")
async def signature_unlock(fname: str = Form(...), password: str = Form(...)):
    """Prueft das Passwort und haelt die entschluesselten Bytes bis Serverstop im RAM."""
    fname = os.path.basename(fname)
    path = os.path.join(SIGN_DIR, fname)
    if not _sig_gesperrt(fname) or not os.path.isfile(path):
        raise HTTPException(404, "Keine passwortgeschützte Signatur")
    with open(path, encoding="utf-8") as f:
        daten = _sig_entschluesseln(f.read(), password)
    sig_unlocked[fname] = daten
    return {"ok": True, "file": fname}


@app.post("/api/signature/password")
async def signature_password(fname: str = Form(...), new_password: str = Form("")):
    """Passwort nachtraeglich setzen, aendern oder (leer) den Schutz entfernen."""
    fname = os.path.basename(fname)
    path = os.path.join(SIGN_DIR, fname)
    if not os.path.isfile(path):
        raise HTTPException(404, "Signatur nicht gefunden")
    basis = fname[:-7] if fname.lower().endswith(".pwdsig") else os.path.splitext(fname)[0]
    if _sig_gesperrt(fname):
        png = sig_unlocked.get(fname)
        if png is None:
            raise HTTPException(401, "Signatur ist gesperrt – erst entsperren")
        if new_password:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_sig_verschluesseln(png, new_password))
            return {"ok": True, "file": fname}
        # Schutz entfernen: entschlüsselte Bytes als normale .png ablegen
        os.remove(path)
        ziel = os.path.join(SIGN_DIR, basis + ".png")
        with open(ziel, "wb") as f:
            f.write(png)
        sig_unlocked.pop(fname, None)
        _alle_stamp_verweise_umbenennen(fname, basis + ".png")
        return {"ok": True, "file": basis + ".png"}
    if not new_password:
        raise HTTPException(400, "Keine Änderung: die Signatur ist nicht geschützt")
    with open(path, "rb") as f:
        png = f.read()
    ziel = os.path.join(SIGN_DIR, basis + ".pwdsig")
    with open(ziel, "w", encoding="utf-8") as f:
        f.write(_sig_verschluesseln(png, new_password))
    os.remove(path)
    sig_unlocked[basis + ".pwdsig"] = png   # soeben gesetzt: sofort entsperrt
    _alle_stamp_verweise_umbenennen(fname, basis + ".pwdsig")
    return {"ok": True, "file": basis + ".pwdsig"}


@app.post("/api/signature/upload")
async def signature_upload(file: UploadFile = File(...), remove_bg: str = Form("1"),
                           password: str = Form(""), threshold: str = Form("232"),
                           name: str = Form("")):
    from PIL import Image
    import io as _io
    name = (name or "").strip() or os.path.splitext(os.path.basename(file.filename or "Signatur"))[0]
    name = "".join(c for c in name if c not in '\\/:*?"<>|') or "Signatur"
    name = os.path.splitext(name)[0][:100] or "Signatur"
    roh = await file.read()
    try:
        img = Image.open(_io.BytesIO(roh))
    except Exception:
        raise HTTPException(400, "Keine Bilddatei")
    try:
        schwelle = int(threshold)
    except (TypeError, ValueError):
        schwelle = 232
    if remove_bg == "1" and schwelle > 0:
        try:
            img = _entferne_weissen_hintergrund(img, schwelle)
        except Exception:
            pass  # ohne Hintergrund-Entfernung weiterbenutzen
    buf = _io.BytesIO()
    img.save(buf, format="PNG")
    png = buf.getvalue()
    if password:
        path = os.path.join(SIGN_DIR, name + ".pwdsig")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_sig_verschluesseln(png, password))
        sig_unlocked[name + ".pwdsig"] = png   # frisch hochgeladen: gleich entsperren
    else:
        path = os.path.join(SIGN_DIR, name + ".png")
        with open(path, "wb") as f:
            f.write(png)
    return {"ok": True, "file": os.path.basename(path)}


def _sig_nmteilen(nm: str):
    """NM-Marker 'PDFW-SIG:datei(:rot)?' -> (dateiname, rotation). Rot ist float (beliebiger Winkel)."""
    if not (nm or "").startswith("PDFW-SIG:"):
        return "", 0.0
    rest = nm[9:]
    fname, _, rot = rest.partition(":")
    try:
        rot = float(rot) if rot else 0.0
    except ValueError:
        rot = 0.0
    return fname, rot % 360.0


def _bbox_gedreht(iw: float, ih: float, rot: float):
    """Achsenparallele Huelle des um rot Grad gedrehten Bildes (iw x ih)."""
    from math import sin, cos, radians
    a = abs(cos(radians(rot)))
    b = abs(sin(radians(rot)))
    return iw * a + ih * b, iw * b + ih * a


@app.post("/api/stamp/{did}")
async def stamp(did: str, page: int = Form(...), x: float = Form(...), y: float = Form(...),
                width: float = Form(140), fname: str = Form(...)):
    """Signatur als VERSCHIEBBARE Stamp-Annotation mit Bild-Erscheinung setzen."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    fname = os.path.basename(fname)
    png = _sig_bytes(fname)
    if png is None:
        if _sig_gesperrt(fname):
            raise HTTPException(401, "Signatur ist passwortgeschützt – erst entsperren")
        raise HTTPException(404, "Signatur nicht gefunden: " + fname)
    from PIL import Image
    import io as _io
    with Image.open(_io.BytesIO(png)) as im:
        iw, ih = im.size
    w = max(30.0, min(float(width), 400.0))
    h = w * ih / iw
    pg = d[page]
    annot = pg.add_stamp_annot(pymupdf.Rect(float(x), float(y), float(x) + w, float(y) + h))
    form_xref = _bild_als_erscheinung(d, png)
    d.xref_set_key(annot.xref, "AP", f"<< /N {form_xref} 0 R >>")
    d.xref_set_key(annot.xref, "NM", f"(PDFW-SIG:{fname})")
    push_undo(did, {"op": "annot-delete", "page": page, "xref": annot.xref})
    return {"ok": True, "xref": annot.xref, "rect": list(annot.rect), "page": page}


def _bild_als_erscheinung(doc, png_bytes: bytes, rot: int = 0) -> int:
    """Baut Form-XObject mit Bild+Alphamaske als Annotation-Erscheinung.
    rot: Vielfache von 90 - das Bild wird vorgedreht eingebettet (BBox passt dann zum
    getauschten Rect). Liefert Form-XRef."""
    from PIL import Image
    import io as _io
    with Image.open(_io.BytesIO(png_bytes)) as im0:
        im = im0.convert("RGBA")
        if rot % 360:
            im = im.rotate(-(rot % 360), expand=True)
        iw, ih = im.size
        rgb = im.convert("RGB").tobytes()
        alpha = im.getchannel("A").tobytes()

    smask = doc.get_new_xref()
    doc.update_object(smask, f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} "
                             f"/ColorSpace /DeviceGray /BitsPerComponent 8 >>")
    doc.update_stream(smask, alpha, new=1)

    img = doc.get_new_xref()
    doc.update_object(img, f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} "
                           f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /SMask {smask} 0 R >>")
    doc.update_stream(img, rgb, new=1)

    form = doc.get_new_xref()
    doc.update_object(form, f"<< /Type /XObject /Subtype /Form /BBox [0 0 {iw} {ih}] "
                            f"/Resources << /XObject << /Img0 {img} 0 R >> >> >>")
    doc.update_stream(form, f"q {iw} 0 0 {ih} 0 0 cm /Img0 Do Q".encode(), new=1)
    return form


@app.post("/api/annot/rotate/{did}")
async def annot_rotate(did: str, page: int = Form(...), xref: int = Form(...),
                       delta: float = Form(90), to: str = Form("")):
    """Signatur drehen - beliebige Winkel. Entweder ZIELwinkel (to="37.5") oder
    delta (z.B. +90 per Kontextmenue). Das Bild wird IMMER vom Original aus um den
    Gesamtwinkel gedreht (keine Qualitaetseinbussen bei wiederholtem Drehen); der
    Kasten (Rect) wird auf die gedrehte Huelle skaliert, damit die Signatur ihre
    Groesse behaelt - zentriert um die bisherige Kastenmitte."""
    d = _doc(did)
    pg = d[page]
    an = pg.load_annot(xref)
    if an is None:
        raise HTTPException(404, "Annotation nicht gefunden")
    nm = an.info.get("id", "") or ""
    fname, rot_alt = _sig_nmteilen(nm)
    png = _sig_bytes(fname) if fname else None
    if png is None:
        if fname and _sig_gesperrt(fname):
            raise HTTPException(401, "Signatur ist passwortgeschützt – erst entsperren")
        raise HTTPException(400, "Signaturdatei nicht mehr vorhanden")
    if to.strip():
        try:
            rot_neu = round(float(to) % 360.0, 2)
        except ValueError:
            raise HTTPException(400, "Ungültiger Winkel")
    else:
        rot_neu = round((rot_alt + float(delta)) % 360.0, 2)
    from PIL import Image
    import io as _io
    with Image.open(_io.BytesIO(png)) as im:
        iw, ih = im.size
    rect_alt = pymupdf.Rect(an.rect)                     # vor allen Aenderungen sichern
    # Skalierung beibehalten: aktuelle Kastenbreite / aktuelle Huellenbreite
    huelle_alt = _bbox_gedreht(iw, ih, rot_alt)
    skala = rect_alt.width / huelle_alt[0] if huelle_alt[0] > 0 else 1.0
    huelle_neu = _bbox_gedreht(iw, ih, rot_neu)
    cx, cy = (rect_alt.x0 + rect_alt.x1) / 2, (rect_alt.y0 + rect_alt.y1) / 2
    wn, hn = skala * huelle_neu[0], skala * huelle_neu[1]
    r = pymupdf.Rect(cx - wn / 2, cy - hn / 2, cx + wn / 2, cy + hn / 2)
    form_xref = _bild_als_erscheinung(d, png, rot_neu)
    d.xref_set_key(xref, "AP", f"<< /N {form_xref} 0 R >>")
    nm_neu = f"(PDFW-SIG:{fname}:{rot_neu:g})" if rot_neu else f"(PDFW-SIG:{fname})"
    d.xref_set_key(xref, "NM", nm_neu)
    an = pg.load_annot(xref)   # frische Annot-Referenz nach AP/NM-Aenderung
    an.set_rect(r)
    push_undo(did, {"op": "sig-rotate", "page": page, "xref": xref,
                    "rect": list(rect_alt), "fname": fname, "rot": rot_alt})
    return {"ok": True, "rot": rot_neu, "rect": list(an.rect)}


@app.get("/api/annots/{did}/{n}")
def annots(did: str, n: int):
    """Liste aller beweglichen Annotationen einer Seite (Signaturen + Freitexte)."""
    d = _doc(did)
    if n < 0 or n >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    out = []
    for a in d[n].annots():
        t = a.type[1]
        if t == "FreeText":
            name = a.info.get("id", "") or ""
            font, size, color = _txt_props(name)   # zentral parsen (Farb-Falle v0.21.11)
            spacing = _txt_spacing(name)
            out.append({
                "xref": a.xref, "type": "text", "rect": list(a.rect),
                "text": (a.info.get("content") or "").rstrip("\n"),
                "font": font, "size": size, "color": color, "spacing": spacing,
                "leading": _txt_leading(name),
            })
        elif t == "Stamp":
            name = a.info.get("id", "") or ""
            sig, rot = _sig_nmteilen(name)  # "PDFW-SIG:" ist 9 Zeichen
            out.append({"xref": a.xref, "type": "sign", "rect": list(a.rect), "file": sig,
                        "rot": rot, "locked": bool(sig) and _sig_gesperrt(sig),
                        "unlocked": bool(sig) and sig in sig_unlocked})
        elif t in ("Square", "Circle", "Line", "Ink"):
            nm = a.info.get("id", "") or ""
            daten = _shape_nm_teile(nm)
            typ = daten["typ"] if daten else {v: k for k, v in SHAPE_ART.items()}.get(t, "rect")
            try:
                breite = daten["breite"] if daten else (a.border_width or 2)
            except Exception:
                breite = 2.0
            stil = (daten.get("stil") if daten else "") or ("C0" if typ == "arrow" else ("N0" if typ == "line" else ""))
            out.append({"xref": a.xref, "type": "shape", "sub": typ, "rect": list(a.rect),
                        "breite": float(breite),
                        "farbe": (daten["strich"] if daten else None) or _farbe_zu_hex(a.colors.get("stroke")),
                        "fuellung": (daten["fuellung"] if daten else "") or "0",
                        "deckkraft": float(daten["deckkraft"]) if daten else round((a.opacity or 1) * 100),
                        "spitze": (stil[:-1] or "N") if stil else "N",
                        "linienstil": stil[-1] if stil else "0",
                        "punkte": (daten.get("punkte") if daten else []) or []})
        elif t in MARKUP_ART.values():
            art = [k for k, v in MARKUP_ART.items() if v == t][0]
            werte = _zahlen_aus(d.xref_get_key(a.xref, "QuadPoints")[1] or "[]")
            H = d[n].rect.height
            quads = []
            for i in range(0, len(werte) - 7, 8):
                xs = [werte[i], werte[i + 2], werte[i + 4], werte[i + 6]]
                ys = [H - v for v in (werte[i + 1], werte[i + 3], werte[i + 5], werte[i + 7])]
                quads.append([round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)])
            bord = _zahlen_aus(d.xref_get_key(a.xref, "Border")[1] or "")
            out.append({"xref": a.xref, "type": "markup", "sub": art, "rect": list(a.rect),
                        "farbe": _farbe_zu_hex(a.colors.get("stroke")) or "FFD300",
                        "deckkraft": round((a.opacity or 1) * 100),
                        "staerke": bord[2] if len(bord) >= 3 and bord[2] > 0 else 1.0,
                        "quads": quads})
    return out


@app.post("/api/annot/move/{did}")
async def annot_move(did: str, page: int = Form(...), xref: int = Form(...), rect: str = Form(...)):
    d = _doc(did)
    pg = d[page]  # Seitenobjekt EINMAL holen - jede d[page]-Zugriff waere ein neues Objekt
    r = pymupdf.Rect(*[float(v) for v in json.loads(rect)])
    an = pg.load_annot(xref)
    if an is None:
        raise HTTPException(404, "Annotation nicht gefunden")
    old_rect = list(an.rect)
    an.set_rect(r)
    if an.type[1] == "FreeText":
        an.update()
        an.set_rect(r)   # update() kann das Rect zuruecksetzen -> danach final setzen
        sp = _txt_spacing(an.info.get("id", "") or "")
        ld = _txt_leading(an.info.get("id", "") or "")
        _freetext_ap_mit_abstand(d, an, pg.rect.height, sp, ld)   # eigener AP bleibt erhalten (MuPDF-AP clippt Mehrzeiliges)
    push_undo(did, {"op": "annot-move", "page": page, "xref": xref, "rect": old_rect,
                    "is_text": an.type[1] == "FreeText"})
    return {"ok": True}


@app.post("/api/annot/delete/{did}")
async def annot_delete(did: str, page: int = Form(...), xref: int = Form(...)):
    d = _doc(did)
    pg = d[page]
    an = pg.load_annot(xref)
    if an is None:
        raise HTTPException(404, "Annotation nicht gefunden")
    t = an.type[1]
    old_rect = list(an.rect)
    if t == "Stamp":
        nm = an.info.get("id", "") or ""
        fname, rot = _sig_nmteilen(nm)
        push_undo(did, {"op": "stamp-recreate", "page": page, "rect": old_rect,
                        "fname": fname, "rot": rot})
    elif t == "FreeText":
        nm = an.info.get("id", "") or ""
        font, size, color = _txt_props(nm)
        sp = _txt_spacing(nm)
        txt = (an.info.get("content") or "").rstrip("\n")
        push_undo(did, {"op": "text-recreate", "page": page, "rect": old_rect, "text": txt,
                        "font": font, "size": size, "color": color, "spacing": sp})
    elif t in ("Square", "Circle", "Line", "Ink"):
        eintrag = _shape_recreate_daten(d, pg, xref, page, old_rect)
        if eintrag:
            push_undo(did, eintrag)
    elif t in MARKUP_ART.values():
        art = [k for k, v in MARKUP_ART.items() if v == t][0]
        werte = _zahlen_aus(d.xref_get_key(xref, "QuadPoints")[1] or "[]")
        H = pg.rect.height
        quads = []
        for i in range(0, len(werte) - 7, 8):
            xs = [werte[i], werte[i + 2], werte[i + 4], werte[i + 6]]
            ys = [H - v for v in (werte[i + 1], werte[i + 3], werte[i + 5], werte[i + 7])]
            quads.append([round(min(xs), 2), round(min(ys), 2), round(max(xs), 2), round(max(ys), 2)])
        bord = _zahlen_aus(d.xref_get_key(xref, "Border")[1] or "")
        if quads:
            push_undo(did, {"op": "markup-recreate", "page": page, "art": art, "quads": quads,
                            "farbe": _farbe_zu_hex(an.colors.get("stroke")) or "FFD300",
                            "deckkraft": round((an.opacity or 1) * 100),
                            "staerke": bord[2] if len(bord) >= 3 and bord[2] > 0 else 1.0})
    pg.delete_annot(an)
    return {"ok": True}


def _shape_recreate_daten(d, pg, xref, page, old_rect):
    """Undo-Eintrag zum Neuaufbau einer Form aus ihrem aktuellen Zustand."""
    an = pg.load_annot(xref)
    if an is None:
        return None
    t = an.type[1]
    nm = an.info.get("id", "") or ""
    daten = _shape_nm_teile(nm)
    typ = daten["typ"] if daten else {v: k for k, v in SHAPE_ART.items()}.get(t, "rect")
    punkte = (daten.get("punkte") if daten else []) or []
    H = pg.rect.height
    if typ in ("line", "arrow") and len(punkte) < 2:
        werte = _zahlen_aus(d.xref_get_key(xref, "L")[1] or "[]")
        if len(werte) >= 4:
            punkte = [[werte[0], H - werte[1]], [werte[2], H - werte[3]]]
    elif typ == "ink" and not punkte:
        punkte = []
        roh = d.xref_get_key(xref, "InkList")[1] or "[]"
        for st in re.findall(r"\[(.*?)\]", roh):
            werte = _zahlen_aus(st)
            pts = [[werte[i], H - werte[i + 1]] for i in range(0, len(werte) - 1, 2)]
            if pts:
                punkte.append(pts)
    try:
        breite = daten["breite"] if daten else (an.border_width or 2)
    except Exception:
        breite = 2.0
    rect_fuer_undo = old_rect
    if punkte:
        if typ in ("line", "arrow"):
            flach = punkte
        else:   # ink: Striche ineinanderflachen
            flach = [p for st in punkte for p in st]
        xs = [p[0] for p in flach]; ys = [p[1] for p in flach]
        rect_fuer_undo = [min(xs), min(ys), max(xs), max(ys)]
    return {"op": "shape-recreate", "page": page, "typ": typ, "rect": rect_fuer_undo,
            "punkte": punkte,
            "breite": float(breite),
            "farbe": (daten["strich"] if daten else None) or _farbe_zu_hex(an.colors.get("stroke")) or "000000",
            "fuellung": (daten["fuellung"] if daten else "") or "0",
            "deckkraft": float(daten["deckkraft"]) if daten else round((an.opacity or 1) * 100),
            "stil": (daten.get("stil") if daten else "") or ("C0" if typ == "arrow" else ("N0" if typ == "line" else ""))}


def _span_in_rect(pg, rect):
    """Dominante Textspanne im Bereich (groesste Schrift) - liefert Groesse, Farbe,
    Schrift-Alias (helv/tiro/cour + Varianten) und die Schreibursprung-Baseline."""
    best = None
    for bl in pg.get_text("dict", clip=pymupdf.Rect(rect))["blocks"]:
        for ln in bl.get("lines", []):
            for sp in ln.get("spans", []):
                if sp["text"].strip() and (best is None or sp["size"] > best["size"]):
                    best = sp
    if not best:
        return None
    f = best["font"].lower()
    fett = "bold" in f or "black" in f
    kursiv = "italic" in f or "oblique" in f
    if "times" in f:
        alias = "tibo" if fett else ("tiit" if kursiv else "tiro")
    elif "cour" in f:
        alias = "cobo" if fett else ("coit" if kursiv else "cour")
    else:
        alias = "hebo" if fett else ("heit" if kursiv else "helv")
    c = best["color"]
    return {"size": round(best["size"], 1),
            "color": [c >> 16 & 255, c >> 8 & 255, c & 255],
            "alias": alias, "origin": list(best["origin"])}

def _zeile_in_rect(pg, rect):
    """Zeile BESTIMMEN aus den eigenen Zeichen: nur Zeichen, deren Mitte im Rect
    liegt (get_text(clip=) liefert bei engen Zeilenabstaenden sonst Woerter der
    Nachbarzeilen mit, deren Boxen um die Font-Steige ueberlappen).
    Liefert Text, Groesse, Farbe, Alias und die EXAKTE Basislinie des ersten
    Zeichens - genau die, die insert_text fuer die Rueckrestoration braucht."""
    rr = pymupdf.Rect(rect)
    erstes = None
    woerter, cur = [], []
    for bl in pg.get_text("rawdict")["blocks"]:
        for ln in bl.get("lines", []):
            for sp in ln.get("spans", []):
                for ch in sp.get("chars", []):
                    bx = ch["bbox"]
                    if not rr.contains(pymupdf.Point((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)):
                        continue
                    if erstes is None:
                        erstes = {"origin": list(ch["origin"]), "size": sp["size"],
                                  "font": sp["font"], "color": sp["color"]}
                    if ch["c"].strip():
                        cur.append(ch["c"])
                    elif cur:
                        woerter.append("".join(cur))
                        cur = []
    if cur:
        woerter.append("".join(cur))
    if erstes is None:
        return None
    f = erstes["font"].lower()
    fett = "bold" in f or "black" in f
    kursiv = "italic" in f or "oblique" in f
    if "times" in f:
        alias = "tibo" if fett else ("tiit" if kursiv else "tiro")
    elif "cour" in f:
        alias = "cobo" if fett else ("coit" if kursiv else "cour")
    else:
        alias = "hebo" if fett else ("heit" if kursiv else "helv")
    c = erstes["color"]
    return {"text": " ".join(woerter), "size": round(erstes["size"], 1),
            "color": [c >> 16 & 255, c >> 8 & 255, c & 255],
            "alias": alias,
            "origin": [round(erstes["origin"][0], 2), round(erstes["origin"][1], 2)]}



@app.get("/api/textspan/{did}/{n}")
def textspan(did: str, n: int, x0: float, y0: float, x1: float, y1: float):
    """Schrifteigenschaften des Texts im Bereich (fuer die Editier-Vorschau)."""
    d = _doc(did)
    if n < 0 or n >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    return _span_in_rect(d[n], [x0, y0, x1, y1]) or {}


def _text_mehrzeilig_einfuegen(pg, origin, text, size, alias, farbe):
    """Text mit evtl. Zeilenumbruechen als echten Seiteninhalt einsetzen;
    Folgezeilen rutschen um size * 1.25 unter die Basislinie."""
    zeilenhoehe = size * 1.25
    for i, zeile in enumerate(text.split("\n")):
        if zeile:
            pg.insert_text((origin[0], origin[1] + i * zeilenhoehe), zeile,
                           fontsize=size, fontname=alias, color=farbe)


@app.post("/api/text/replace/{did}")
async def text_replace(did: str, page: int = Form(...), rect: str = Form(...), text: str = Form(""),
                       size: str = Form(""), font: str = Form(""), color: str = Form("")):
    """Originaltext im Bereich ersetzen (kein Bildtext): alten Text tilgen (Redaction),
    den neuen als echten Seiteninhalt einsetzen - mehrzeilig moeglich; Groesse, Schrift
    und Farbe optional uebersteuerbar (0-1-Farbwerte, 4-Zeichen-Alias wie 'hebo').
    Leerer Text = nur entfernen."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    r = pymupdf.Rect(*[float(v) for v in json.loads(rect)])
    text = text.replace("\r\n", "\n")
    pg = d[page]
    info = _span_in_rect(pg, r) or {}
    size_w = float(info.get("size") or 11.0)
    farbe = tuple((info.get("color") or [0, 0, 0])[i] / 255 for i in range(3))
    alias = info.get("alias") or "helv"
    if font and font in FONTS:
        alias = font
    try:
        if float(size or 0) > 0:
            size_w = float(size)
    except ValueError:
        pass
    if color:
        try:
            farbe = tuple(float(c) for c in color.split(","))
        except ValueError:
            pass
    origin = tuple(info.get("origin") or (r.x0, r.y1 - size_w * 0.25))
    text_alt = " ".join(pg.get_text("text", clip=r).split())
    pg.add_redact_annot(r)
    pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    if text.strip():
        _text_mehrzeilig_einfuegen(pg, origin, text, size_w, alias, farbe)
    push_undo(did, {"op": "text-replace", "page": page, "rect": list(r),
                    "text_alt": text_alt, "text_neu": text, "origin": list(origin),
                    "size": size_w, "color": list(farbe), "font": alias})
    return {"ok": True, "size": size_w, "font": alias}


@app.post("/api/text/blockreplace/{did}")
async def text_blockreplace(did: str, page: int = Form(...), zeilen: str = Form(...),
                            size: str = Form(""), font: str = Form(""), color: str = Form("")):
    """Mehrere Originaltext-Zeilen in einem Zug tilgen (Block-/Mehrfachauswahl im
    Originaltext-Editor). EIN Undo-Eintrag, der JEDE Zeile an ihrer eigenen
    Position wieder herstellt. zeilen = JSON-Liste [{"rect": [x0,y0,x1,y1]}, ...]."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    try:
        liste = json.loads(zeilen)
    except ValueError:
        raise HTTPException(400, "zeilen muss eine JSON-Liste sein")
    if not isinstance(liste, list) or not liste:
        raise HTTPException(400, "mindestens eine Zeile noetig")
    try:
        size_tb = float(size or 0)
    except ValueError:
        size_tb = 0.0
    farbe_tb = None
    if color:
        try:
            farbe_tb = tuple(float(c) for c in color.split(","))
        except ValueError:
            pass
    pg = d[page]
    eintraege = []
    for z in liste:
        try:
            r = pymupdf.Rect(*[float(v) for v in z["rect"]])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(400, "je Zeile rect [x0,y0,x1,y1] noetig")
        # Zeile ueber die EIGENEN Zeichen bestimmen - exakte Basislinie fuer das
        # Undo (_span_in_rect wuerde bei engen Zeilen die Nachbarspanne liefern).
        eigene = _zeile_in_rect(pg, r)
        li_size = size_tb if size_tb > 0 else float((eigene or {}).get("size") or 11.0)
        li_farbe = farbe_tb or tuple(((eigene or {}).get("color") or [0, 0, 0])[i] / 255 for i in range(3))
        li_alias = font if font in FONTS else ((eigene or {}).get("alias") or "helv")
        origin = tuple((eigene or {}).get("origin") or (r.x0, r.y1 - li_size * 0.25))
        pg.add_redact_annot(r)
        eintraege.append({"rect": [round(v, 1) for v in r],
                          "origin": [round(origin[0], 2), round(origin[1], 2)],
                          "text_alt": (eigene or {}).get("text", ""), "size": li_size,
                          "font": li_alias, "color": list(li_farbe)})
    pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    push_undo(did, {"op": "origzeilen", "page": page, "zeilen": eintraege})
    # zeilen mit zurueckgeben: Client leitet daraus Baseline + Zeilenabstand des
    # Originals ab, damit der ersetzende Textblock am gleichen Raster steht.
    return {"ok": True, "n": len(eintraege), "zeilen": eintraege}


FONTS = {"helv": "Helvetica", "hebo": "Helvetica Fett", "heit": "Helvetica Kursiv", "hebi": "Helvetica Fett-Kursiv",
         "tiro": "Times", "tibo": "Times Fett", "tiit": "Times Kursiv", "tibi": "Times Fett-Kursiv",
         "cour": "Courier", "cobo": "Courier Fett", "coit": "Courier Kursiv", "cobi": "Courier Fett-Kursiv"}

# BaseFont-Namen fuer eigene Appearance-Streams (Zeichenabstand via Tc)
FONTS_AP = {"helv": "Helvetica", "hebo": "Helvetica-Bold", "heit": "Helvetica-Oblique",
            "hebi": "Helvetica-BoldOblique", "tiro": "Times-Roman", "tibo": "Times-Bold",
            "tiit": "Times-Italic", "tibi": "Times-BoldItalic", "cour": "Courier",
            "cobo": "Courier-Bold", "coit": "Courier-Oblique", "cobi": "Courier-BoldOblique"}


def _font_xref(doc, basefont):
    """Minimales Type1-Font-Objekt (Base14) fuer Appearance-Ressourcen."""
    x = doc.get_new_xref()
    doc.update_object(x, f"<< /Type /Font /Subtype /Type1 /BaseFont /{basefont} "
                         f"/Encoding /WinAnsiEncoding >>")
    return x


def _base14_name(font):
    """Font-Angabe fuer add_freetext_annot: nur Base14-Aliase sind erlaubt.
    Dokument-Schriften ('doc~...') erzeugen dort nur den Platzhalter-AP - das
    echte Aussehen setzt _freetext_ap_mit_abstand sofort danach."""
    return font if font in FONTS else "helv"


def _pdf_string(text):
    """Text als PDF-Literalstring (WinAnsi-Bytes, Klammern/Backslash escaped)."""
    out = bytearray(b"(")
    for byte in text.encode("cp1252", "replace"):
        if byte in (0x28, 0x29, 0x5C):
            out.append(0x5C)
        out.append(byte)
    out.append(0x29)
    return bytes(out)


def _txt_spacing(nm):
    """Zeichenabstand (pt) aus einem PDFW-TXT-NM-Marker (5. Feld, 0 wenn fehlt)."""
    if nm.startswith("PDFW-TXT:"):
        teile = nm.split(":", 4)
        if len(teile) >= 5:
            try:
                return float(teile[4])
            except ValueError:
                pass
    return 0.0




def _txt_leading(nm):
    """Zeilenabstand (pt) aus dem PDFW-TXT-NM-Marker (6. Feld; 0 = Standard
    size * 1,25). Wird beim Bearbeiten von Originaltext gesetzt, damit der
    ersetzende Textblock den Zeilenraster des Originals einhaelt."""
    if nm.startswith("PDFW-TXT:"):
        teile = nm.split(":", 5)
        if len(teile) >= 6:
            try:
                return float(teile[5])
            except ValueError:
                pass
    return 0.0


def _docfont_aufloesen(d, font_angabe):
    """'doc~xref~basefont' -> (pdf_font_xref, pymupdf.Font) oder None.
    xref kann nach Speichern mit GarbageCollection wandern - dann per
    basefont ueber alle Seiten neu suchen."""
    teile = font_angabe.split("~")
    if len(teile) < 3:
        return None
    try:
        xref = int(teile[1])
    except ValueError:
        return None
    basefont = teile[2]
    res = _docfont_lesen(d, str(id(d)) + basefont, xref)
    if res is not None:
        return res
    for pno in range(d.page_count):
        for eintrag in d.get_page_fonts(pno, full=True):
            if eintrag[3] == basefont:
                res = _docfont_lesen(d, str(id(d)) + basefont, eintrag[0])
                if res is not None:
                    return res
    return None


def _freetext_ap_mit_abstand(doc, an, page_h, spacing, leading=0.0, did_hint=None):
    """Ersetzt den Appearance-Stream einer Freitext-Annotation durch eine
    Darstellung mit Zeichenabstand (PDF-Operator Tc, in Punkten) und
    Zeilenabstand. Eigenschaften (Rect, Text, Schrift) kommen aus der
    Annotation selbst; leading in pt (0 = size * 1,25).
    Schriften 'doc~xref~basefont' (eingebettete Dokument-Schriften) werden
    per Glyph-ID-Stream gesetzt; fuer Zeichen ohne Glyph (Subsets!) springt
    der Stream auf Helvetica um."""
    r = an.rect
    text = (an.info.get("content") or "").replace("\r\n", "\n")
    nm = an.info.get("id", "") or ""
    font, size, color = _txt_props(nm)
    basefont = FONTS_AP.get(font, "Helvetica")
    color01 = _txt_farbe01(color)   # Marker ist 0-1; /255 war die zweite Schwarz-Falle
    docfont = None
    if font.startswith("doc~"):
        docfont = _docfont_aufloesen(doc, font)
        if docfont is None:
            font = "helv"   # Schrift nicht mehr im Dokument: Base14-Fallback
    fontx = _font_xref(doc, basefont)
    helvx = _font_xref(doc, "Helvetica") if docfont else 0
    zeilenhoehe = leading if leading > 0 else size * 1.25
    teile = [f"BT {color01[0]:.4g} {color01[1]:.4g} {color01[2]:.4g} rg"]
    if spacing:
        teile.append(f"{spacing:.4g} Tc")
    for i, zeile in enumerate(text.split("\n")):
        baseline = (page_h - r.y0) - size * 0.9 - i * zeilenhoehe
        if docfont:
            fx, fontobj, _buf = docfont
            segmente = _gid_ap_text(fontobj, zeile)
            if not segmente:
                continue
            teile.append(f"1 0 0 1 {r.x0 + 2:.2f} {baseline:.2f} Tm")
            for ziel, inhalt in segmente:
                if ziel == "doc":
                    teile.append(f"/F0 {size:.4g} Tf <{inhalt}> Tj")
                else:
                    teile.append(f"/F1 {size:.4g} Tf ({inhalt}) Tj")
        else:
            teile.append(f"1 0 0 1 {r.x0 + 2:.2f} {baseline:.2f} Tm "
                         f"/F0 {size:.4g} Tf {_pdf_string(zeile).decode('latin-1')} Tj")
    teile.append("ET")
    apx = doc.get_new_xref()
    fonts_res = f"/F0 {fontx} 0 R" if not docfont else f"/F0 {docfont[0]} 0 R /F1 {helvx} 0 R"
    doc.update_object(apx, f"<< /Type /XObject /Subtype /Form /BBox [{r.x0:.2f} {page_h - r.y1:.2f} {r.x1:.2f} {page_h - r.y0:.2f}] "
                           f"/Resources << /Font << {fonts_res} >> >> >>")
    doc.update_stream(apx, ("q " + " ".join(teile) + " Q").encode("latin-1"), new=1)
    doc.xref_set_key(an.xref, "AP", f"<< /N {apx} 0 R >>")


@app.post("/api/annot/text/{did}")
async def annot_text(did: str, page: int = Form(...), rect: str = Form(...), text: str = Form(""),
                     size: float = Form(11), font: str = Form("helv"), color: str = Form("0,0,0"),
                     xref: int = Form(0), spacing: str = Form("0"), leading: str = Form("0")):
    """Freitext-Annotation anlegen oder (bei xref>0) mit neuen Eigenschaften neu erzeugen.
    spacing = Zeichenabstand, leading = Zeilenabstand in Punkten (0 = Standard
    size * 1,25; beim Ersetzen von Originaltext wird der gemessene Zeilenraster
    des Originals uebergeben, damit die Zeilen an ihrer Position bleiben)."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    if font.startswith("doc~"):
        if _docfont_aufloesen(d, font) is None:
            font = "helv"   # eingebettete Schrift nicht (mehr) vorhanden
    elif font not in FONTS:
        font = "helv"
    try:
        spacing_f = float(spacing or 0)
    except ValueError:
        spacing_f = 0.0
    try:
        leading_f = float(leading or 0)
    except ValueError:
        leading_f = 0.0
    r = pymupdf.Rect(*[float(v) for v in json.loads(rect)])
    col = tuple(float(c) for c in color.split(","))
    pg = d[page]
    o_font, o_size, o_color, o_text = "helv", 11.0, [0, 0, 0], ""
    o_spacing = 0.0
    o_leading = 0.0
    if xref:
        old = pg.load_annot(xref)
        if old is not None:
            r = pymupdf.Rect(old.rect)  # Rect der alten Annotation behalten (Groesse via Move aendern)
            old_nm = old.info.get("id", "") or ""
            o_font, o_size, o_color = _txt_props(old_nm)
            o_text = (old.info.get("content") or "").rstrip("\n")
            o_spacing = _txt_spacing(old_nm)
            o_leading = _txt_leading(old_nm)
            pg.delete_annot(old)
    a = pg.add_freetext_annot(r, text, fontsize=float(size), fontname=_base14_name(font), text_color=col)
    a.update()
    # Eigenschaften im NM-Marker konservieren (PyMuPDF-Ruecklesen ist unzuverlaessig)
    marker = f"PDFW-TXT:{font}:{size}:{col[0]},{col[1]},{col[2]}:{spacing_f}:{leading_f}"
    d.xref_set_key(a.xref, "NM", f"({marker})")
    # IMMER eigener Appearance-Stream: MuPDFs Freitext-AP rendert mehrzeilig mit
    # ~2,4-fachem Zeilenabstand und clippt Folgelinien an der BBox weg (4. Zeile
    # unsichtbar). Unser AP nutzt das Leading aus dem Marker (Default 1,25).
    _freetext_ap_mit_abstand(d, a, pg.rect.height, spacing_f, leading_f)
    if xref:
        push_undo(did, {"op": "text-restore", "page": page, "new_xref": a.xref,
                        "old": {"rect": list(r), "text": o_text, "font": o_font,
                                "size": o_size, "color": o_color, "spacing": o_spacing,
                                "leading": o_leading}})
    else:
        push_undo(did, {"op": "annot-delete", "page": page, "xref": a.xref})
    return {"ok": True, "xref": a.xref}


@app.post("/api/inserttext/{did}")
async def inserttext(did: str, page: int = Form(...), x: float = Form(...), y: float = Form(...),
                     text: str = Form(...), size: float = Form(11)):
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    d[page].insert_text((float(x), float(y)), text, fontsize=float(size))
    return {"ok": True, "page": page}


@app.post("/api/delete/{did}")
async def delete_text(did: str, page: int = Form(...), rects: str = Form(...)):
    """rects: JSON-Liste [x0,y0,x1,y1] - entfernt Text in diesen Bereichen (Redaction)."""
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    areas = json.loads(rects)
    if not areas:
        return {"ok": True, "removed": 0}
    pg = d[page]
    for r in areas:
        pg.add_redact_annot(pymupdf.Rect(r[0], r[1], r[2], r[3]))
    pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    return {"ok": True, "removed": len(areas)}


@app.get("/api/print/{did}")
def print_view(did: str):
    """Druckansicht: alle Seiten MIT Annotationen und ausgefuellten Formularen."""
    d = _doc(did)
    imgs = []
    for pno in range(d.page_count):
        pix = d[pno].get_pixmap(dpi=120, annots=True)
        b64 = base64.encodebytes(pix.tobytes("png")).decode().replace("\n", "")
        imgs.append(f'<img src="data:image/png;base64,{b64}">')
    html = ("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<style>body{margin:0}img{display:block;width:100%;page-break-after:always}"
            "@page{margin:0}</style></head><body>" + "".join(imgs) + "</body></html>")
    return HTMLResponse(html)


@app.get("/api/druckinfo/{did}")
def druck_info(did: str):
    """Seitenzahl + Seitenmasse (Punkte) fuer den Druckpfad des Wrappers: der
    Wrapper druckt per GDI in DRUCKERAUFLOESUNG - der alte iframe-/window.print-
    Weg rastered nur Bildschirmqualitaet (unscharfer Ausdruck, Nutzer-Fund)."""
    d = _doc(did)
    return {"pages": d.page_count,
            "groessen": [[round(p.rect.width, 2), round(p.rect.height, 2)] for p in d]}


@app.get("/api/druckseite/{did}")
def druck_seite(did: str, nr: int = 0, dpi: int = 300, annots: int = 1):
    """Eine Seite als PNG in DRUCKaufloesung - annots=1 (Standard) mit
    Annotationen und Formularwerten, annots=0 pures Papier ohne Signaturen/
    Markierungen/Formulare (Druckdialog-Option). dpi geklemmt: 600 reicht
    jedem Laser, mehr waere reiner Speicherfraß."""
    d = _doc(did)
    if nr < 0 or nr >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    dpi = max(72, min(int(dpi), 600))
    pix = d[nr].get_pixmap(dpi=dpi, annots=bool(annots))
    return Response(content=pix.tobytes("png"), media_type="image/png")


@app.get("/api/search/{did}")
def search(did: str, q: str):
    d = _doc(did)
    if not q.strip():
        return {"hits": []}
    hits = []
    for pno in range(d.page_count):
        try:
            for r in d[pno].search_for(q):
                hits.append({"page": pno, "rect": [r.x0, r.y0, r.x1, r.y1]})
        except Exception:
            pass
        if len(hits) >= 800:
            break
    return {"hits": hits}


@app.post("/api/rotate/{did}")
async def rotate(did: str, page: int = Form(...), delta: int = Form(90)):
    d = _doc(did)
    pg = d[page]
    pg.set_rotation((pg.rotation + int(delta)) % 360)
    push_undo(did, {"op": "rotate", "page": page, "delta": -int(delta)})
    return {"ok": True, "rotation": pg.rotation}


@app.post("/api/deletepage/{did}")
async def deletepage(did: str, page: int = Form(...)):
    d = _doc(did)
    if d.page_count <= 1:
        raise HTTPException(400, "Die letzte Seite kann nicht geloescht werden")
    d.delete_page(page)
    undo_stacks[did] = []   # Seitenindizes verschieben sich - Stapel sicherheitshalber leeren
    return {"ok": True, "pages": d.page_count}


@app.post("/api/undo/{did}")
def undo(did: str):
    d = _doc(did)
    stack = undo_stacks.get(did) or []
    if not stack:
        return {"ok": True, "undone": False}
    e = stack.pop()
    if e["page"] >= d.page_count:
        return {"ok": True, "undone": False}
    pg = d[e["page"]]
    op = e["op"]
    if op == "annot-delete":
        an = pg.load_annot(e["xref"])
        if an is not None:
            pg.delete_annot(an)
    elif op == "annot-move":
        an = pg.load_annot(e["xref"])
        if an is not None:
            r = pymupdf.Rect(e["rect"])
            an.set_rect(r)
            if an.type[1] == "FreeText":
                an.update()
                an.set_rect(r)
    elif op == "text-restore":
        an = pg.load_annot(e["new_xref"])
        if an is not None:
            pg.delete_annot(an)
        o = e["old"]
        a = pg.add_freetext_annot(pymupdf.Rect(o["rect"]), o["text"], fontsize=o["size"],
                                  fontname=_base14_name(o["font"]), text_color=tuple(o["color"]))
        a.update()
        sp = float(o.get("spacing") or 0)
        ld = float(o.get("leading") or 0)
        d.xref_set_key(a.xref, "NM",
                       f"(PDFW-TXT:{o['font']}:{o['size']}:{o['color'][0]},{o['color'][1]},{o['color'][2]}:{sp}:{ld})")
        _freetext_ap_mit_abstand(d, a, pg.rect.height, sp, ld)   # immer eigener AP
    elif op == "stamp-recreate":
        fname = os.path.basename(e.get("fname") or "")
        png = _sig_bytes(fname) if fname else None
        if png is not None:
            rot = int(e.get("rot") or 0)
            annot = pg.add_stamp_annot(pymupdf.Rect(e["rect"]))
            form_xref = _bild_als_erscheinung(d, png, rot)
            d.xref_set_key(annot.xref, "AP", f"<< /N {form_xref} 0 R >>")
            nm = f"(PDFW-SIG:{fname}:{rot:g})" if rot else f"(PDFW-SIG:{fname})"
            d.xref_set_key(annot.xref, "NM", nm)
    elif op == "sig-rotate":
        an = pg.load_annot(e["xref"])
        if an is not None:
            fname = e.get("fname") or ""
            png = _sig_bytes(fname) if fname else None
            rot_alt = int(e.get("rot") or 0)
            if png is None:
                pg.delete_annot(an)   # Signaturdatei weg - besser loeschen als falsch herum
            else:
                form_xref = _bild_als_erscheinung(d, png, rot_alt)
                d.xref_set_key(e["xref"], "AP", f"<< /N {form_xref} 0 R >>")
                nm = f"(PDFW-SIG:{fname}:{rot_alt:g})" if rot_alt else f"(PDFW-SIG:{fname})"
                d.xref_set_key(e["xref"], "NM", nm)
                an = pg.load_annot(e["xref"])
                an.set_rect(pymupdf.Rect(e["rect"]))
    elif op == "text-recreate":
        a = pg.add_freetext_annot(pymupdf.Rect(e["rect"]), e["text"], fontsize=e["size"],
                                  fontname=_base14_name(e["font"]), text_color=tuple(e["color"]))
        a.update()
        sp = float(e.get("spacing") or 0)
        ld = float(e.get("leading") or 0)
        d.xref_set_key(a.xref, "NM",
                       f"(PDFW-TXT:{e['font']}:{e['size']}:{e['color'][0]},{e['color'][1]},{e['color'][2]}:{sp}:{ld})")
        _freetext_ap_mit_abstand(d, a, pg.rect.height, sp, ld)   # immer eigener AP
    elif op in ("image-move", "image-rotate"):
        o = e
        alt_r = pymupdf.Rect(*o["alt"])
        neu_r = pymupdf.Rect(*o["neu"])
        xr_u = o.get("xrefs") or [o["xref"]]
        # Undo als EIGENE Chirurgie (v0.21.15): Platzierung an der Zielstelle
        # selbst finden und mit inverser Matrix zurueckschieben - robust ueber
        # beliebig lange Undo-Ketten, keine Byte-Buchhaltung.
        plaetze = [_bild_platzierung(d, pg, v, neu_r) for v in xr_u]
        zurueck = False
        if all(plaetze) and o.get("matrizen"):
            # Undo = die VORHER-Matrix wortwörtlich neu anwenden (Chirurgie).
            # Exakt, ohne inverse Komposition - der Zustand unmittelbar vor dem
            # Operationstag wird wiederhergestellt.
            basis_map = {id(p): tuple(m) for p, m in zip(plaetze, o["matrizen"])}

            def mfn(p, h, _bm=basis_map):
                return _bm.get(id(p)) or _bm[next(iter(_bm))]
            zurueck = bool(_bild_chirurgie(d, pg, plaetze, mfn))
        if all(plaetze) and not zurueck and not o.get("matrizen"):
            hoehe = pg.rect.height
            mfn = lambda p, h: (alt_r.width, 0, 0, alt_r.height,
                                alt_r.x0, h - alt_r.y1)
            zurueck = bool(_bild_chirurgie(d, pg, plaetze, mfn))
        if not zurueck:                            # Deckel-Pfad (Legacy/unsaubere Bloecke)
            deckel_r = _weissdeckel(neu_r)
            deckelfarbe, _gleich = _deckelfarbe(pg, deckel_r)   # nie verweigern: Notfall weiss
            pg.draw_rect(deckel_r, color=None, fill=deckelfarbe or (1, 1, 1), overlay=True)
            for v in xr_u:   # gestapelte Ebenen gemeinsam zurueck
                _bild_einsetzen(d, pg, alt_r, v, _platzierung_farben(d, pg, v, alt_r))
    elif op == "text-replace":
        o = e
        o0 = o["origin"]
        neu_zeilen = (o["text_neu"] or "").split("\n") if o["text_neu"] else []
        breite_neu = max([pymupdf.get_text_length(z, fontsize=o["size"], fontname=o["font"])
                          for z in neu_zeilen], default=0)
        hoehe_neu = len(neu_zeilen) * o["size"] * 1.25
        fl = pymupdf.Rect(min(o["rect"][0], o0[0]),
                          min(o["rect"][1], o0[1] - o["size"]),
                          max(o["rect"][2], o0[0] + breite_neu),
                          max(o["rect"][3], o0[1] + hoehe_neu + o["size"] * 0.3))
        pg.add_redact_annot(fl)              # neuen Text tilgen ...
        pg.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
        if o["text_alt"]:                    # ... und Original zurueckschreiben
            _text_mehrzeilig_einfuegen(pg, tuple(o0), o["text_alt"], o["size"],
                                       o["font"], tuple(o["color"]))
    elif op == "origzeilen":                 # Block-Redaction: JEDE Zeile an ihrer eigenen Position
        for z in e["zeilen"]:
            if z["text_alt"]:
                _text_mehrzeilig_einfuegen(pg, tuple(z["origin"]), z["text_alt"],
                                           z["size"], z["font"], tuple(z["color"]))
    elif op == "field":
        for w in pg.widgets():
            if w.field_name == e["name"]:
                if w.field_type_string in ("CheckBox", "RadioButton"):
                    w.field_value = e["value"].lower() in ("1", "true", "yes", "an", "x")
                    w.update()
                else:
                    _feld_wert_setzen(d, w, e["value"])
    elif op == "rotate":
        pg.set_rotation((pg.rotation + e["delta"]) % 360)
    elif op == "shape-recreate":
        try:
            _shape_anlegen(d, pg, e["typ"], pymupdf.Rect(e["rect"]), e.get("punkte") or [],
                           e.get("breite", 2), e.get("farbe", "000000"),
                           e.get("fuellung", "0"), e.get("deckkraft", 100), e.get("stil", ""))
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(400, "Form konnte nicht wiederhergestellt werden: " + str(ex))
    elif op == "markup-recreate":
        try:
            rects = [pymupdf.Rect(q[0], q[1], q[2], q[3]) for q in e["quads"]]
            _markup_anlegen(d, pg, e["art"], rects, e.get("farbe", "FFD300"),
                            e.get("deckkraft", 40), e.get("staerke", 1))
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(400, "Markierung konnte nicht wiederhergestellt werden: " + str(ex))
    elif op == "shape-move":
        an = pg.load_annot(e["xref"])
        if an is not None:
            _shape_transformieren(d, pg, e["xref"], pymupdf.Rect(e["alt"]), pymupdf.Rect(e["neu"]))
    elif op == "style-set":
        if pg.load_annot(e["xref"]) is not None:
            _style_setzen(d, pg, e["xref"], e["alt"])
    return {"ok": True, "undone": True, "page": e["page"], "op": op, "left": len(stack)}


# ---------- Formen (Rechteck/Oval/Linie/Pfeil/Tinte) & Text-Markierungen ----------
#
# Formen sind echte PDF-Annotationen (Square/Circle/Line/Ink) mit Stil im
# PDFW-SHAPE-NM-Marker, Markierungen sind Markup-Annotationen (Highlight/
# Underline/StrikeOut/Squiggly) mit eigenem Appearance-Stream: MuPDFs AP
# kennt keine Strichstaerke bei Unter-/Durchstreichen, und set_rect wird fuer
# Markup schlicht abgelehnt ("no Rect property") - Verschieben geht also nur
# ueber QuadPoints + Rect + eigenen AP in einem Zug.
#
# PDF-Koordinaten: die API arbeitet durchgaengig mit TOP-basierten
# Koordinaten (wie der Rest des Servers); die PDF-Keys QuadPoints/L/InkList
# sind bottom-up - die Umrechnung passiert nur in den _qp/_l/_ilk-Helfern.

SHAPE_ART = {"rect": "Square", "oval": "Circle", "line": "Line", "arrow": "Line", "ink": "Ink"}
SHAPE_NAME = {"rect": "Rechteck", "oval": "Oval", "line": "Linie", "arrow": "Pfeil", "ink": "Tinte"}
MARKUP_ART = {"h": "Highlight", "u": "Underline", "s": "StrikeOut", "q": "Squiggly"}
MARKUP_NAME = {"h": "Marker", "u": "Unterstrichen", "s": "Durchgestrichen", "q": "Wellenlinie"}


def _hex_zu_farbe(s):
    s = (s or "").strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None


def _farbe_zu_hex(t):
    if not t:
        return "0"
    return "%02X%02X%02X" % tuple(min(255, max(0, round(c * 255))) for c in t[:3])


def _zahlen_aus(s):
    """Floats aus einem PDF-Array-String ([x y ...] / [[..] [..]]) ziehen."""
    import re
    return [float(v) for v in re.findall(r"-?\d+\.?\d*", s)]


def _shape_nm(typ, breite, strich, fuellung, deckkraft, stil="", punkte=""):
    return f"PDFW-SHAPE:{typ}:{breite:g}:{strich}:{fuellung}:{round(deckkraft)}:{stil}:{punkte}"


def _shape_nm_teile(nm):
    """NM-Marker -> dict oder None (fremde Annotation ohne Marker).
    stil: Pfeilspitzen (C=gefuellt, O=offen, N=keine; 1 Zeichen = Endspitze,
    2 Zeichen = Anfang+Ende) + Linienstil (0=durchgezogen, 1=gestrichelt,
    2=gepunktet), z. B. 'C0', 'OO1'. Alte Marker (vor v0.18.5) ohne Stil-
    Feld: arrow -> C0, line -> N0."""
    if not (nm or "").startswith("PDFW-SHAPE:"):
        return None
    try:
        teile = nm.split(":")   # Felder enthalten nie ':' (Farben hex, Zahlen, Punkte)
        if len(teile) == 7:      # alter Marker (vor v0.18.5): ohne Stil-Feld
            _, typ, breite, strich, fuellung, deckkraft, punkte = teile
            stil = ""
        elif len(teile) >= 8:
            _, typ, breite, strich, fuellung, deckkraft, stil, punkte = teile[:7] + [":".join(teile[7:])]
        else:
            raise ValueError("PDFW-SHAPE-Marker zu kurz")
        daten = {"typ": typ, "breite": float(breite), "strich": strich,
                 "fuellung": fuellung, "deckkraft": float(deckkraft)}
        if not stil:
            daten["stil"] = "C0" if typ == "arrow" else ("N0" if typ == "line" else "")
        else:
            daten["stil"] = stil
        if typ in ("line", "arrow"):
            daten["punkte"] = [[float(v) for v in p.split(",")] for p in punkte.split(";")] if punkte else []
        elif typ == "ink":
            daten["punkte"] = [[[float(v) for v in p.split(",")] for p in st.split(";")]
                               for st in punkte.split("|")] if punkte else []
        else:
            daten["punkte"] = []
        return daten
    except (ValueError, IndexError):
        return None


def _punkte_zu_nm(typ, punkte):
    if typ in ("line", "arrow") and len(punkte) >= 2:
        return ";".join(f"{p[0]:.1f},{p[1]:.1f}" for p in punkte[:2])
    if typ == "ink" and punkte:
        return "|".join(";".join(f"{p[0]:.1f},{p[1]:.1f}" for p in st) for st in punkte)
    return ""


LE_PDF = {"C": "/ClosedArrow", "O": "/OpenArrow", "N": "/None"}


def _stil_teile(stil):
    """'C0'/'OO1'/... -> (startspitze, endspitze, linienstil)."""
    stil = stil or ""
    if len(stil) >= 2:
        return stil[0], stil[1], stil[-1]
    if len(stil) == 1:
        return "N", stil[0], "0"
    return "N", "N", "0"


def _line_stil_anwenden(doc, a, breite, stil):
    """/LE (Pfeilspitzen), /IC (gefuellte Spitzen) und /Border mit Dash-Muster
    direkt setzen (vor update()). MuPDF fuellt ClosedArrow NUR bei gesetztem
    /IC - ohne sieht die Spitze im PDF hohl aus, waehrend das Overlay sie
    fuellt (WYSIWYG-Fix v0.18.7). Fuellfarbe = Strichfarbe, wie im Overlay."""
    start, ende, linienstil = _stil_teile(stil)
    if start != "N" or ende != "N":
        doc.xref_set_key(a.xref, "LE", f"[{LE_PDF.get(start, '/None')} {LE_PDF.get(ende, '/None')}]")
    if "C" in (start, ende):
        c = a.colors.get("stroke")
        if c:
            doc.xref_set_key(a.xref, "IC", "[" + " ".join(f"{v:g}" for v in c) + "]")
    else:
        doc.xref_set_key(a.xref, "IC", "null")   # keine gefuellte Spitze mehr: /IC entfernen
    b = max(0.2, float(breite))
    if linienstil == "1":
        doc.xref_set_key(a.xref, "Border", f"[0 0 {b:g} [5 4]]")
    elif linienstil == "2":
        doc.xref_set_key(a.xref, "Border", f"[0 0 {b:g} [0.6 2.6]]")


def _shape_anlegen(doc, pg, typ, rect_r, punkte, breite, strich, fuellung, deckkraft, stil=""):
    """Form-Annotation anlegen (auch fuer Undo-Neuaufbau). punkte: line/arrow
    [[x1,y1],[x2,y2]], ink [[ [x,y],... ],...], sonst []. stil: Spitzen+Linienstil
    fuer line/arrow (leer = Voreinstellung: arrow C0, line N0)."""
    if typ == "arrow":
        stil = stil or "C0"
    elif typ == "line":
        stil = stil or "N0"
    farbe = _hex_zu_farbe(strich) or (0, 0, 0)
    fuellung = (fuellung or "0").strip()
    fill = _hex_zu_farbe(fuellung) if fuellung not in ("", "0") else None
    if typ == "rect":
        a = pg.add_rect_annot(rect_r)
    elif typ == "oval":
        a = pg.add_circle_annot(rect_r)
    elif typ in ("line", "arrow"):
        p1, p2 = punkte[0], punkte[1]
        a = pg.add_line_annot(pymupdf.Point(p1[0], p1[1]), pymupdf.Point(p2[0], p2[1]))
    elif typ == "ink":
        a = pg.add_ink_annot([[ [p[0], p[1]] for p in st] for st in punkte])   # float-Paare, KEINE Point-Objekte
    else:
        raise HTTPException(400, "Unbekannter Formtyp: " + typ)
    try:
        a.set_colors(stroke=farbe, fill=fill)
        a.set_border(width=max(0.2, float(breite)))
        if float(deckkraft) < 100:
            a.set_opacity(max(0.05, float(deckkraft) / 100))
    except Exception:
        pass  # fremde/leere Objekte: Stil so gut wie moeglich setzen
    if typ in ("line", "arrow"):
        _line_stil_anwenden(doc, a, breite, stil)
    a.update()   # Standard-AP aus den Eigenschaften erzeugen (nur Stamp-AP nie updaten!)
    doc.xref_set_key(a.xref, "NM",
                     f"({_shape_nm(typ, float(breite), strich, fuellung, float(deckkraft), stil, _punkte_zu_nm(typ, punkte))})")
    return a


def _qp_string(rects, H):
    teile = []
    for r in rects:
        teile.append(f"{r.x0:.2f} {H - r.y0:.2f} {r.x1:.2f} {H - r.y0:.2f} "
                     f"{r.x0:.2f} {H - r.y1:.2f} {r.x1:.2f} {H - r.y1:.2f}")
    return "[" + " ".join(teile) + "]"


def _markup_ap_setzen(doc, xref, rects, art, farbe_hex, staerke, H):
    """Eigener Appearance-Stream: Markup mit Strichstaerke und genauer Lage.
    Die AP-BBox wird vom Viewer auf das Annot-/Rect gemappt - BBox und Rect
    muessen identisch sein, sonst wandert die Darstellung."""
    c = _hex_zu_farbe(farbe_hex) or (1, 0.85, 0)
    x0 = min(r.x0 for r in rects); y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects); y1 = max(r.y1 for r in rects)
    ops = []
    if art == "h":
        ops.append(f"{c[0]:.4g} {c[1]:.4g} {c[2]:.4g} rg")
        for r in rects:
            ops.append(f"{r.x0:.2f} {H - r.y1:.2f} {r.x1 - r.x0:.2f} {r.y1 - r.y0:.2g} re f")
    else:
        w = max(0.3, float(staerke))
        ops.append(f"{c[0]:.4g} {c[1]:.4g} {c[2]:.4g} RG {w:.4g} w 1 J")
        for r in rects:
            if art == "u":
                y = H - r.y1 + 1.2
                ops.append(f"{r.x0:.2f} {y:.2f} m {r.x1:.2f} {y:.2f} l S")
            elif art == "s":
                y = H - (r.y0 + r.y1) / 2
                ops.append(f"{r.x0:.2f} {y:.2f} m {r.x1:.2f} {y:.2f} l S")
            else:   # q: Wellenlinie entlang der Unterkante
                ybase = H - r.y1 + 2
                pts = []
                i = 0
                x = r.x0
                while x < r.x1:
                    pts.append(f"{x:.2f} {ybase + (2.2 if i % 2 == 0 else 0):.2f}")
                    x += 4
                    i += 1
                if pts:
                    ops.append("m " + " l ".join(pts) + " l S")
    apx = doc.get_new_xref()
    doc.update_object(apx, f"<< /Type /XObject /Subtype /Form "
                           f"/BBox [{x0:.2f} {H - y1:.2f} {x1:.2f} {H - y0:.2f}] >>")
    doc.update_stream(apx, (" ".join(ops)).encode("latin-1"), new=1)
    doc.xref_set_key(xref, "AP", f"<< /N {apx} 0 R >>")


def _markup_anlegen(doc, pg, art, rects, farbe_hex, deckkraft, staerke):
    H = pg.rect.height
    ql = [pymupdf.Quad(pymupdf.Point(r.x0, r.y0), pymupdf.Point(r.x1, r.y0),
                       pymupdf.Point(r.x0, r.y1), pymupdf.Point(r.x1, r.y1)) for r in rects]
    adder = {"h": pg.add_highlight_annot, "u": pg.add_underline_annot,
             "s": pg.add_strikeout_annot, "q": pg.add_squiggly_annot}[art]
    a = adder(quads=ql)
    a.set_colors(stroke=_hex_zu_farbe(farbe_hex) or (1, 0.85, 0))
    if float(deckkraft) < 100:
        a.set_opacity(max(0.05, float(deckkraft) / 100))
    a.update()
    _markup_konsistent(doc, a.xref, rects, art, farbe_hex, float(staerke), H)
    return a


def _markup_konsistent(doc, xref, rects, art, farbe_hex, staerke, H):
    """QuadPoints, Rect, Border und AP einer Markup-Annotation in Einklang
    bringen (gleiche Stelle, gleiche Groesse - sonst mappt der Viewer die AP
    falsch)."""
    doc.xref_set_key(xref, "QuadPoints", _qp_string(rects, H))
    x0 = min(r.x0 for r in rects); y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects); y1 = max(r.y1 for r in rects)
    doc.xref_set_key(xref, "Rect", f"[{x0:.2f} {H - y1:.2f} {x1:.2f} {H - y0:.2f}]")
    if art != "h":
        doc.xref_set_key(xref, "Border", f"[0 0 {max(0.3, float(staerke)):.4g}]")
    _markup_ap_setzen(doc, xref, rects, art, farbe_hex, staerke, H)


@app.get("/api/textquads/{did}/{n}")
def textquads(did: str, n: int, x0: float, y0: float, x1: float, y1: float):
    """Wort-Umrahmungen (Top-Koordinaten) im Auswahlrechteck - Grundlage fuer
    Markierungen: Nur ueberlappte Woerter werden markiert, nicht ganze Zeilen."""
    d = _doc(did)
    if n < 0 or n >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    pg = d[n]
    sel = pymupdf.Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    sel_h = max(0.1, sel.y1 - sel.y0)
    treffer = []
    for w in pg.get_text("words"):
        wr = pymupdf.Rect(w[:4])
        ix = min(wr.x1, sel.x1) - max(wr.x0, sel.x0)
        if ix <= 0:
            continue
        iy = min(wr.y1, sel.y1) - max(wr.y0, sel.y0)
        wr_h = wr.y1 - wr.y0
        zy = (wr.y0 + wr.y1) / 2
        # Duennes Auswahlband (waagerechter Zug entlang einer Zeile - die natuerliche
        # Geste zum Markieren): Wort zaehlt, wenn sein Hoehenzentrum im leicht
        # erweiterten Band liegt oder es die Haelfte der KLEINEREN Hoehe ueberlappt.
        # Dicke Auswahl: uebliche 25%-Flaechen-Regel.
        trifft = (sel.y0 - 2 <= zy <= sel.y1 + 2) or iy >= 0.5 * min(sel_h, wr_h) \
                 or (iy > 0 and ix * iy >= 0.25 * (wr.x1 - wr.x0) * wr_h)
        if trifft:
            treffer.append([round(wr.x0, 2), round(wr.y0, 2), round(wr.x1, 2), round(wr.y1, 2), w[4]])
    treffer.sort(key=lambda q: (q[1], q[0]))
    return {"quads": [q[:4] for q in treffer], "text": " ".join(q[4] for q in treffer)}


@app.post("/api/annot/shape/{did}")
async def annot_shape(did: str, page: int = Form(...), typ: str = Form(...),
                      rect: str = Form(...), punkte: str = Form("[]"),
                      breite: float = Form(2), farbe: str = Form("000000"),
                      fuellung: str = Form("0"), deckkraft: float = Form(100),
                      spitze: str = Form(""), linienstil: str = Form("")):
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    if typ not in SHAPE_ART:
        raise HTTPException(400, "Unbekannter Formtyp: " + typ)
    pg = d[page]
    try:
        pts = json.loads(punkte) if punkte else []
        rect_r = pymupdf.Rect(*[float(v) for v in json.loads(rect)])
    except (ValueError, TypeError):
        raise HTTPException(400, "Ungültige Geometrie")
    if typ in ("line", "arrow"):
        if len(pts) < 2:
            raise HTTPException(400, "Linie braucht zwei Punkte")
        alle = pts[:2]
        rect_r = pymupdf.Rect(min(alle[0][0], alle[1][0]), min(alle[0][1], alle[1][1]),
                              max(alle[0][0], alle[1][0]), max(alle[0][1], alle[1][1]))
        if rect_r.get_area() < 4:   # winziger Klick: kleine Diagonale daraus machen
            alle = [pts[0], [pts[1][0] + 8, pts[1][1] + 8]]
            rect_r = pymupdf.Rect(alle[0][0], alle[0][1], alle[1][0], alle[1][1])
        pts = alle
    elif typ == "ink":
        if not pts or not any(len(st) >= 2 for st in pts):
            raise HTTPException(400, "Tinte braucht Punkte")
        xs = [p[0] for st in pts for p in st]; ys = [p[1] for st in pts for p in st]
        rect_r = pymupdf.Rect(min(xs), min(ys), max(xs), max(ys))
    rect_r = rect_r | pymupdf.Rect(rect_r.x0, rect_r.y0, rect_r.x0 + 2, rect_r.y0 + 2)  # Mindestgroesse
    stil = ""
    if typ in ("line", "arrow"):
        spitze = spitze if spitze in ("C", "O", "N", "CC", "OO", "CO", "OC", "CN", "NC", "ON", "NO") else ("C" if typ == "arrow" else "N")
        if linienstil not in ("0", "1", "2"):
            linienstil = "0"
        stil = spitze + linienstil
    a = _shape_anlegen(d, pg, typ, rect_r, pts, breite, farbe, fuellung, deckkraft, stil)
    push_undo(did, {"op": "annot-delete", "page": page, "xref": a.xref})
    return {"ok": True, "xref": a.xref, "rect": list(a.rect)}


@app.post("/api/annot/markup/{did}")
async def annot_markup(did: str, page: int = Form(...), art: str = Form(...),
                       quads: str = Form(...), farbe: str = Form("FFD300"),
                       deckkraft: float = Form(40), staerke: float = Form(1)):
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    if art not in MARKUP_ART:
        raise HTTPException(400, "Unbekannte Markierungsart: " + art)
    try:
        rects = [pymupdf.Rect(q[0], q[1], q[2], q[3]) for q in json.loads(quads)]
    except (ValueError, TypeError, IndexError):
        raise HTTPException(400, "quads muss JSON-Liste [x0,y0,x1,y1] sein")
    if not rects:
        raise HTTPException(400, "Keine Auswahl übergeben")
    pg = d[page]
    a = _markup_anlegen(d, pg, art, rects, farbe, deckkraft, staerke)
    push_undo(did, {"op": "annot-delete", "page": page, "xref": a.xref})
    return {"ok": True, "xref": a.xref, "rect": list(a.rect)}


def _shape_transformieren(doc, pg, xref, alt_r, neu_r):
    """Form/Markierung verschieben oder skalieren: alt_r = aktuelle BBox,
    neu_r = Ziel-BBox. Punkte (L/InkList/QuadPoints) werden proportional
    umgerechnet - nur set_rect wuerde die Grafik verzerren bzw. bei Markup
    (kein Rect per API) gar nicht gehen."""
    an = pg.load_annot(xref)
    if an is None:
        raise HTTPException(404, "Annotation nicht gefunden")
    t = an.type[1]
    H = pg.rect.height
    # Vorzeichen bewusst erlaubt (alt_r/neu_r duerfen gespiegelt sein, x1<x0 -
    # Undo eines Flips v0.18.7): sx/sy < 0 spiegeln die Punkte mit.
    sx = (neu_r.x1 - neu_r.x0) / (alt_r.x1 - alt_r.x0) if alt_r.x1 != alt_r.x0 else 1
    sy = (neu_r.y1 - neu_r.y0) / (alt_r.y1 - alt_r.y0) if alt_r.y1 != alt_r.y0 else 1

    def skaliere(x, y):   # Top-Koordinaten: alt_r-BBox auf neu_r-BBox abbilden
        return (neu_r.x0 + (x - alt_r.x0) * sx, neu_r.y0 + (y - alt_r.y0) * sy)

    if t in ("Square", "Circle"):
        # MuPDF legt den ZIEHPFAD in das uebergebene Rect, der sichtbare Kasten
        # (inkl. Strichbreite) wird um halbe Strichbreite GROESSER. Fuer
        # "sichtbares Rechteck = Ziel" vorher um halbe Strichbreite einziehen.
        daten = _shape_nm_teile(an.info.get("id", "") or "") or {}
        b = float(daten.get("breite") or 0) / 2
        an.set_rect(pymupdf.Rect(neu_r.x0 + b, neu_r.y0 + b, neu_r.x1 - b, neu_r.y1 - b))
        an.update()
        an = pg.load_annot(xref)
        an.set_rect(pymupdf.Rect(neu_r.x0 + b, neu_r.y0 + b, neu_r.x1 - b, neu_r.y1 - b))
    elif t == "Line":
        daten = _shape_nm_teile(an.info.get("id", "") or "") or {}
        werte = _zahlen_aus(doc.xref_get_key(xref, "L")[1] or "[]")
        if len(werte) >= 4:
            p1 = skaliere(werte[0], H - werte[1])
            p2 = skaliere(werte[2], H - werte[3])
            doc.xref_set_key(xref, "L", f"[{p1[0]:.2f} {H - p1[1]:.2f} {p2[0]:.2f} {H - p2[1]:.2f}]")
            # NM-Punkte mitziehen - sonst zeichnet das Overlay nach einem Reload
            # die ALTE Stelle (latenter Bug seit v0.18.5, der Flip hat ihn aufgedeckt)
            if daten:
                doc.xref_set_key(xref, "NM", "(" + _shape_nm(
                    daten.get("typ", "line"), float(daten.get("breite") or 2),
                    daten.get("strich") or "000000", daten.get("fuellung", "0"),
                    float(daten.get("deckkraft") or 100), daten.get("stil") or "",
                    _punkte_zu_nm(daten.get("typ", "line"), [p1, p2])) + ")")
        an = pg.load_annot(xref)
        an.update()   # Rect folgt /L automatisch
    elif t == "Ink":
        daten = _shape_nm_teile(an.info.get("id", "") or "") or {}
        roh = doc.xref_get_key(xref, "InkList")[1] or "[]"
        stroks = []
        neu_punkte = []   # Struktur erhalten: eine Liste je Strich
        neu_stroke = []
        for st in re.findall(r"\[(.*?)\]", roh):
            werte = _zahlen_aus(st)
            pts = []
            for i in range(0, len(werte) - 1, 2):
                x, y = skaliere(werte[i], H - werte[i + 1])
                pts.append(f"{x:.2f} {H - y:.2f}")
                neu_stroke.append([x, y])
            if pts:
                stroks.append("[" + " ".join(pts) + "]")
                neu_punkte.append(neu_stroke)
                neu_stroke = []
        if stroks:
            doc.xref_set_key(xref, "InkList", "[" + "".join(stroks) + "]")
            # NM-Striche mitziehen (wie bei Line - sonst alte Stelle nach Reload)
            if daten:
                doc.xref_set_key(xref, "NM", "(" + _shape_nm(
                    daten.get("typ", "ink"), float(daten.get("breite") or 2),
                    daten.get("strich") or "000000", daten.get("fuellung", "0"),
                    float(daten.get("deckkraft") or 100), daten.get("stil") or "",
                    _punkte_zu_nm("ink", neu_punkte)) + ")")
        an = pg.load_annot(xref)
        an.update()
    elif t in MARKUP_ART.values():
        art = [k for k, v in MARKUP_ART.items() if v == t][0]
        nm_farbe = _farbe_zu_hex(an.colors.get("stroke")) if an.colors.get("stroke") else "FFD300"
        staerke = 1.0
        try:
            bord = _zahlen_aus(doc.xref_get_key(xref, "Border")[1] or "")
            if len(bord) >= 3 and bord[2] > 0:
                staerke = bord[2]
        except Exception:
            pass
        werte = _zahlen_aus(doc.xref_get_key(xref, "QuadPoints")[1] or "[]")
        rects = []
        for i in range(0, len(werte) - 7, 8):
            xs = [werte[i], werte[i + 2], werte[i + 4], werte[i + 6]]
            ys = [H - v for v in (werte[i + 1], werte[i + 3], werte[i + 5], werte[i + 7])]
            ecken = [skaliere(x, y) for x, y in zip(xs, ys)]
            rects.append(pymupdf.Rect(min(p[0] for p in ecken), min(p[1] for p in ecken),
                                      max(p[0] for p in ecken), max(p[1] for p in ecken)))
        if rects:
            _markup_konsistent(doc, xref, rects, art, nm_farbe, staerke, H)
    else:
        raise HTTPException(400, "Dieser Annotationstyp ist nicht verschiebbar: " + t)


def _style_lesen(d, pg, xref):
    """Aktueller Stil einer Form/Markierung (fuer Undo)."""
    an = pg.load_annot(xref)
    if an is None:
        raise HTTPException(404, "Annotation nicht gefunden")
    t = an.type[1]
    if t in MARKUP_ART.values():
        bord = _zahlen_aus(d.xref_get_key(xref, "Border")[1] or "")
        return {"art": "markup", "sub": [k for k, v in MARKUP_ART.items() if v == t][0],
                "farbe": _farbe_zu_hex(an.colors.get("stroke")),
                "deckkraft": round((an.opacity or 1) * 100),
                "staerke": bord[2] if len(bord) >= 3 and bord[2] > 0 else 1.0}
    daten = _shape_nm_teile(an.info.get("id", "") or "") or {}
    typ = daten.get("typ") or {v: k for k, v in SHAPE_ART.items()}.get(t, "rect")
    stil = daten.get("stil") or ("C0" if typ == "arrow" else ("N0" if typ == "line" else ""))
    return {"art": "shape", "sub": typ,
            "farbe": daten.get("strich") or _farbe_zu_hex(an.colors.get("stroke")),
            "fuellung": daten.get("fuellung", "0"),
            "deckkraft": daten.get("deckkraft", round((an.opacity or 1) * 100)),
            "breite": daten.get("breite", 2.0),
            "stil": stil}


def _style_setzen(doc, pg, xref, werte):
    """Stil einer Form/Markierung anwenden (Endpoint und Undo teilen sich das)."""
    an = pg.load_annot(xref)
    if an is None:
        raise HTTPException(404, "Annotation nicht gefunden")
    t = an.type[1]
    farbe = werte.get("farbe") or ""
    hexf = _hex_zu_farbe(farbe) if farbe else None
    deckkraft = float(werte.get("deckkraft") or 100)
    if t in MARKUP_ART.values():
        art = [k for k, v in MARKUP_ART.items() if v == t][0]
        an.set_colors(stroke=hexf or an.colors.get("stroke") or (1, 0.85, 0))
        an.set_opacity(max(0.05, deckkraft / 100))
        an.update()
        werte_qp = _zahlen_aus(doc.xref_get_key(xref, "QuadPoints")[1] or "[]")
        H = pg.rect.height
        rects = []
        for i in range(0, len(werte_qp) - 7, 8):
            xs = [werte_qp[i], werte_qp[i + 2], werte_qp[i + 4], werte_qp[i + 6]]
            ys = [H - v for v in (werte_qp[i + 1], werte_qp[i + 3], werte_qp[i + 5], werte_qp[i + 7])]
            rects.append(pymupdf.Rect(min(xs), min(ys), max(xs), max(ys)))
        if rects:
            _markup_konsistent(doc, xref, rects, art,
                               farbe or _farbe_zu_hex(an.colors.get("stroke")),
                               float(werte.get("staerke") or 1), H)
        return
    if t == "Line":
        # Spitzen (/LE) und Linienstil (/Border mit Dash) direkt setzen - width
        # steckt mit im Border-Array, set_border wuerde das Dash wieder loeschen.
        daten = _shape_nm_teile(an.info.get("id", "") or "") or {}
        alt_stil = daten.get("stil") or "N0"
        if werte.get("stil"):
            stil = werte["stil"]          # Undo-Eintrag traegt den GESAMTEN alten Stil
        else:
            spitze = werte.get("spitze") if werte.get("spitze") else alt_stil[:-1]
            linienstil = werte.get("linienstil") if werte.get("linienstil") else alt_stil[-1]
            stil = (spitze or "N") + (linienstil or "0")
        if hexf is not None:
            try:
                an.set_colors(stroke=hexf)
            except Exception:
                pass
        if deckkraft < 100:
            try:
                an.set_opacity(max(0.05, deckkraft / 100))
            except Exception:
                pass
        breite = float(werte.get("breite") or daten.get("breite") or 2)
        _line_stil_anwenden(doc, an, breite, stil)
        an.update()
        doc.xref_set_key(xref, "NM", "(" + _shape_nm(
            daten.get("typ", "line"), breite,
            werte.get("farbe") or daten.get("strich") or "000000",
            werte.get("fuellung") if werte.get("fuellung") is not None else daten.get("fuellung", "0"),
            deckkraft if werte.get("deckkraft") is not None else daten.get("deckkraft", 100),
            stil, _punkte_zu_nm(daten.get("typ", "line"), daten.get("punkte", []))) + ")")
        return
    if hexf is not None or werte.get("fuellung") is not None:
        fill = None
        if (werte.get("fuellung") or "0") not in ("", "0"):
            fill = _hex_zu_farbe(werte["fuellung"])
        try:
            an.set_colors(stroke=hexf or an.colors.get("stroke"), fill=fill)
        except Exception:
            pass
    if werte.get("breite"):
        try:
            an.set_border(width=max(0.2, float(werte["breite"])))
        except Exception:
            pass
    if deckkraft < 100:
        try:
            an.set_opacity(max(0.05, deckkraft / 100))
        except Exception:
            pass
    an.update()
    alt = _shape_nm_teile(an.info.get("id", "") or "") or {}
    typ = alt.get("typ") or {v: k for k, v in SHAPE_ART.items()}.get(t, "rect")
    alt_stil = alt.get("stil") or ("C0" if typ == "arrow" else ("N0" if typ == "line" else ""))
    doc.xref_set_key(xref, "NM", "(" + _shape_nm(
        typ,
        float(werte.get("breite") or alt.get("breite") or 2),
        werte.get("farbe") or alt.get("strich") or "000000",
        werte.get("fuellung") if werte.get("fuellung") is not None else alt.get("fuellung", "0"),
        deckkraft if werte.get("deckkraft") is not None else alt.get("deckkraft", 100),
        werte.get("stil") or alt_stil,
        _punkte_zu_nm(typ, alt.get("punkte", []))) + ")")


@app.post("/api/annot/shapemove/{did}")
async def annot_shapemove(did: str, page: int = Form(...), xref: int = Form(...),
                          alt: str = Form(...), neu: str = Form(...)):
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    pg = d[page]
    alt_r = pymupdf.Rect(*[float(v) for v in json.loads(alt)])
    neu_r = pymupdf.Rect(*[float(v) for v in json.loads(neu)])
    _shape_transformieren(d, pg, xref, alt_r, neu_r)
    an = pg.load_annot(xref)
    push_undo(did, {"op": "shape-move", "page": page, "xref": xref,
                    "alt": list(neu_r), "neu": list(alt_r)})   # invertiert: zurueckskalieren
    return {"ok": True, "rect": list(an.rect) if an else list(neu_r)}


@app.post("/api/annot/style/{did}")
async def annot_style(did: str, page: int = Form(...), xref: int = Form(...),
                      breite: str = Form(""), farbe: str = Form(""),
                      fuellung: str = Form(""), deckkraft: str = Form(""),
                      staerke: str = Form(""), spitze: str = Form(""),
                      linienstil: str = Form("")):
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    pg = d[page]
    if pg.load_annot(xref) is None:
        raise HTTPException(404, "Annotation nicht gefunden")
    alt = _style_lesen(d, pg, xref)
    neu = {}
    for k, v in (("breite", breite), ("farbe", farbe), ("fuellung", fuellung),
                 ("deckkraft", deckkraft), ("staerke", staerke),
                 ("spitze", spitze), ("linienstil", linienstil)):
        if v != "":
            neu[k] = v
    if not neu:
        return {"ok": True}
    _style_setzen(d, pg, xref, neu)
    push_undo(did, {"op": "style-set", "page": page, "xref": xref, "alt": alt})
    return {"ok": True}


# ---------- OCR: unsichtbare Textebene fuer Seiten ohne Text (Scans) ----------
#
# Tesseract ist im PyMuPDF-Wheel enthalten (1.28.x) - es fehlen nur die
# Sprachdaten (tessdata/deu+eng.traineddata neben der EXE bzw. im Projekt).
# Pro Seite: OCR-Textpage -> Zeilen gruppieren -> je Zeile unsichtbaren Text
# (render_mode=3) an der OCR-Baseline einsetzen. Kein Undo (wie Redaction):
# die Ebene ist rein zusaetzlich, veraendert nichts Sichtbares.

@app.get("/api/ocr/info/{did}")
def ocr_info(did: str):
    """Welche Seiten haben bereits Text (und kommen fuer OCR nicht in Frage)?"""
    d = _doc(did)
    ohne = []
    for i in range(d.page_count):
        if not d[i].get_text().strip():
            ohne.append(i)
    return {"pages": d.page_count, "seiten_ohne_text": ohne,
            "tessdata": sorted(f[:-12] for f in os.listdir(TESSDATA)
                               if f.endswith(".traineddata")) if os.path.isdir(TESSDATA) else []}


@app.post("/api/ocr/{did}")
async def ocr_seite(did: str, page: int = Form(...), lang: str = Form("deu+eng"),
                    dpi: int = Form(300)):
    d = _doc(did)
    if page < 0 or page >= d.page_count:
        raise HTTPException(404, "Seite existiert nicht")
    verfuegbar = ([f[:-12] for f in os.listdir(TESSDATA) if f.endswith(".traineddata")]
                  if os.path.isdir(TESSDATA) else [])
    for code in lang.split("+"):
        if code and code not in verfuegbar:
            raise HTTPException(400, f"Sprachdaten '{code}' fehlen (tessdata-Ordner)")
    pg = d[page]
    if pg.get_text().strip():
        return {"ok": True, "skip": True, "zeilen": 0}
    try:
        tp = pg.get_textpage_ocr(language=lang, dpi=max(150, min(400, int(dpi))),
                                 full=True, tessdata=TESSDATA)
    except Exception as e:
        raise HTTPException(500, "OCR fehlgeschlagen: " + str(e)[:300])
    woerter = pg.get_text("words", textpage=tp)
    zeilen = {}
    for w in woerter:
        zeilen.setdefault((w[5], w[6]), []).append(w)
    eingefuegt = 0
    for key in sorted(zeilen):
        ws = sorted(zeilen[key], key=lambda w: w[0])
        text = " ".join(w[4] for w in ws)
        if not text.strip():
            continue
        x0 = min(w[0] for w in ws); y0 = min(w[1] for w in ws)
        x1 = max(w[2] for w in ws); y1 = max(w[3] for w in ws)
        hoehe = max(4.0, y1 - y0)
        size = hoehe * 0.8
        # Baseline: Unterkante minus ~18 % Versalhoehe (wie bei echtem Text)
        rc = pg.insert_text((x0, y1 - hoehe * 0.18), text, fontsize=size,
                            fontname="helv", render_mode=3)
        if rc >= 0:
            eingefuegt += 1
    return {"ok": True, "skip": False, "zeilen": eingefuegt}


# ---------- Eingebettete Schriften des Dokuments (Zeichensatz-Auswahl) ----------
#
# Eingebettete Fonts (TTF/OTF/CFF) werden per xref extrahiert: die UI laedt
# sie als @font-face fuer das Overlay, der Server nutzt sie fuer Freitext-APs
# (Glyph-ID-Streams, Identity-H) und beim Einbrennen. Subsets (XXXXXX+Name)
# enthalten nur die im Dokument benutzten Zeichen - fehlende Glyphen fallen
# auf Helvetica zurueck.

_docfont_cache = {}   # cache-schluessel -> (pdf_font_xref, pymupdf.Font, buffer)


def _docfont_lesen(d, cache_schluessel, fontxref):
    """Font einbetten (einmalig je Dokument+Font) und als Objekt liefern."""
    if cache_schluessel in _docfont_cache:
        return _docfont_cache[cache_schluessel]
    try:
        _, ext, _, buf = d.extract_font(fontxref)
    except Exception:
        buf = None
    if not buf or (ext or "") not in ("ttf", "otf", "cff"):
        _docfont_cache[cache_schluessel] = None
        return None
    font = pymupdf.Font(fontbuffer=buf)
    # irgendeine Seite als Ressourcen-Anker: insert_font legt das Font-Objekt an
    fx = 0
    for pg in d:
        try:
            fx = pg.insert_font(fontname=f"PWd{fontxref}", fontbuffer=buf)
            break
        except Exception:
            continue
    if not fx:
        _docfont_cache[cache_schluessel] = None
        return None
    _docfont_cache[cache_schluessel] = (fx, font, buf)
    return _docfont_cache[cache_schluessel]


@app.get("/api/fonts/{did}")
def schriften(did: str):
    """Eingebettete Schriften aller Seiten (dedupliziert), nur vollstaendig
    extrahierbare sind auswaehlbar."""
    d = _doc(did)
    gesehen = {}
    for pno in range(d.page_count):
        for eintrag in d.get_page_fonts(pno, full=True):
            xref, ext, typ, basefont = eintrag[0], eintrag[1], eintrag[2], eintrag[3]
            if xref in gesehen or xref <= 0:
                continue
            name = basefont[7:] if re.match(r"^[A-Z]{6}\+", basefont) else basefont
            gesehen[xref] = {"xref": xref, "name": name, "basefont": basefont,
                             "typ": typ, "ext": ext,
                             "subset": bool(re.match(r"^[A-Z]{6}\+", basefont)),
                             "nutzbar": ext in ("ttf", "otf", "cff")}
    return list(gesehen.values())


@app.get("/api/font/file/{did}/{xref}")
def schrift_datei(did: str, xref: int):
    d = _doc(did)
    try:
        name, ext, typ, buf = d.extract_font(xref)
    except Exception:
        raise HTTPException(404, "Schrift nicht extrahierbar")
    if not buf:
        raise HTTPException(404, "Schrift nicht eingebettet")
    media = {"ttf": "font/ttf", "otf": "font/otf", "cff": "application/octet-stream",
             "pfa": "application/octet-stream", "pfb": "application/octet-stream"}.get(ext, "application/octet-stream")
    datei = re.sub(r"[^A-Za-z0-9_.-]", "_", name or f"font{xref}") + "." + (ext or "bin")
    return Response(content=buf, media_type=media,
                    headers={"Content-Disposition": f'inline; filename="{datei}"'})


def _gid_ap_text(font, text):
    """Text als Glyph-ID-Segmente: Laufe mit Glyphen im Doc-Font, Luecken
    (Subset ohne Zeichen) als WinAnsi-Helvetica-Segment."""
    segmente = []   # (docfont|helv, inhalt) - inhalt: hexstring oder pdf-string
    def push(ziel, inhalt):
        if inhalt and segmente and segmente[-1][0] == ziel:
            segmente[-1] = (ziel, segmente[-1][1] + inhalt)
        elif inhalt:
            segmente.append((ziel, inhalt))
    for ch in text:
        gid = font.has_glyph(ord(ch)) if font else 0
        if ch in "\r\n\t":
            continue   # Zeilenumbrueche werden vom Aufrufer in separate Tm aufgeteilt
        if gid and gid > 0:
            push("doc", f"{gid:04X}")
        else:
            push("helv", _pdf_string(ch).decode("latin-1"))
    return segmente


# ---------- KI-Assistent (BYOK: Anbieter + API-Schluessel vom Nutzer) ----------
#
# Die Konfiguration liegt in einstellungen.json unter dem Schluessel "ki"
# (Modelle mit URL/Schluessel + Aufgaben-Zuordnung) - der Server liest sie
# nur. Alle Anbieter-Anfragen laufen ueber den lokalen Server: keine Keys im
# Browser, kein CORS. Streaming: der Server zieht SSE vom Anbieter und reicht
# Text-Deltas als Chunks weiter (urllib, kein zusaetzliches Bundle-Paket).

AI_PRESETS = {
    "openai":     {"name": "OpenAI", "url": "https://api.openai.com/v1", "art": "openai"},
    "zai":        {"name": "z.ai (GLM)", "url": "https://api.z.ai/api/paas/v4", "art": "openai"},
    "openrouter": {"name": "OpenRouter", "url": "https://openrouter.ai/api/v1", "art": "openai"},
    "anthropic":  {"name": "Anthropic (Claude)", "url": "https://api.anthropic.com", "art": "anthropic"},
    "google":     {"name": "Google (Gemini)", "url": "https://generativelanguage.googleapis.com/v1beta", "art": "google"},
    "ollama":     {"name": "Ollama (lokal)", "url": "http://localhost:11434/v1", "art": "openai"},
    "custom":     {"name": "OpenAI-kompatibel (eigene URL)", "url": "", "art": "openai"},
}


def _ki_einstellungen():
    try:
        with open(PREFS_FILE, encoding="utf-8") as f:
            daten = json.load(f)
        ki = daten.get("ki")
    except Exception:
        ki = None
    return ki if isinstance(ki, dict) else {}


def _ki_modell(mid: str):
    for m in _ki_einstellungen().get("modelle", []):
        if isinstance(m, dict) and m.get("id") == mid:
            return m
    raise HTTPException(404, "KI-Modell nicht konfiguriert (Id " + mid + ")")


def _ai_headers(art, key):
    h = {"Content-Type": "application/json"}
    if art == "anthropic":
        h["x-api-key"] = key
        h["anthropic-version"] = "2023-06-01"
    elif art == "google":
        pass   # Key haengt in der URL
    else:
        h["Authorization"] = "Bearer " + key
    return h


def _ai_url_basis(modell):
    url = (modell.get("url") or "").strip().rstrip("/")
    art = modell.get("art") or "openai"
    if not url:
        preset = AI_PRESETS.get(modell.get("anbieter", ""))
        url = (preset or {}).get("url", "")
        art = (preset or {}).get("art", "openai")
    return url, art


@app.get("/api/ai/models")
def ai_modelle(url: str, key: str = "", art: str = "openai"):
    """Verfuegbare Modelle eines Anbieters abrufen (Konfigurationsdialog,
    'Liste der Modelle aktualisieren')."""
    import urllib.request
    import urllib.parse
    basis = url.strip().rstrip("/")
    if not basis:
        raise HTTPException(400, "Keine URL angegeben")
    try:
        if art == "google":
            req = urllib.request.Request(basis + "/models?key=" + urllib.parse.quote(key),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                daten = json.loads(resp.read().decode("utf-8"))
            ids = sorted(m["name"].split("/")[-1] for m in daten.get("models", [])
                         if isinstance(m, dict) and m.get("name"))
        else:
            pfad = "/models" if art == "anthropic" else "/models"
            req = urllib.request.Request(basis + pfad, headers=_ai_headers(art, key))
            with urllib.request.urlopen(req, timeout=30) as resp:
                daten = json.loads(resp.read().decode("utf-8"))
            ids = sorted(str(m.get("id")) for m in daten.get("data", [])
                         if isinstance(m, dict) and m.get("id"))
    except Exception as e:
        detail = ""
        if hasattr(e, "read"):
            try:
                detail = " – " + e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
        raise HTTPException(502, "Anbieter nicht erreichbar: " + str(e)[:200] + detail)
    return {"modelle": ids}


def _ai_strom(modell, nachrichten, system):
    """Generator: Text-Deltas vom Anbieter (SSE) als utf-8-Chunks weiterreichen."""
    import urllib.request
    import urllib.error
    import urllib.parse
    basis, art = _ai_url_basis(modell)
    key = modell.get("key") or ""
    name = modell.get("model") or ""
    try:
        if art == "anthropic":
            koerper = {"model": name, "max_tokens": 4096, "stream": True,
                       "messages": [{"role": m["role"], "content": m["content"]} for m in nachrichten]}
            if system:
                koerper["system"] = system
            url = basis + "/v1/messages"
        elif art == "google":
            rollen = {"user": "user", "assistant": "model"}
            inhalt = [{"role": rollen.get(m["role"], "user"), "parts": [{"text": m["content"]}]}
                      for m in nachrichten]
            koerper = {"contents": inhalt, "generationConfig": {"maxOutputTokens": 8192}}
            if system:
                koerper["systemInstruction"] = {"parts": [{"text": system}]}
            url = basis + f"/models/{name}:streamGenerateContent?alt=sse"
            if key:
                url += "&key=" + urllib.parse.quote(key)
        else:
            koerper = {"model": name, "stream": True, "messages": []}
            if system:
                koerper["messages"].append({"role": "system", "content": system})
            koerper["messages"] += [{"role": m["role"], "content": m["content"]} for m in nachrichten]
            url = basis + "/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(koerper).encode("utf-8"),
                                     headers=_ai_headers(art, key), method="POST")
        with urllib.request.urlopen(req, timeout=300) as resp:
            for zeile in resp:
                zeile = zeile.decode("utf-8", "replace").strip()
                if not zeile.startswith("data:"):
                    continue
                daten_str = zeile[5:].strip()
                if daten_str in ("", "[DONE]"):
                    continue
                try:
                    ereignis = json.loads(daten_str)
                except ValueError:
                    continue
                stueck = ""
                if art == "anthropic":
                    if ereignis.get("type") == "content_block_delta":
                        stueck = (ereignis.get("delta") or {}).get("text") or ""
                elif art == "google":
                    try:
                        stueck = ereignis["candidates"][0]["content"]["parts"][0]["text"]
                    except (KeyError, IndexError, TypeError):
                        stueck = ""
                else:
                    try:
                        stueck = ereignis["choices"][0]["delta"].get("content") or ""
                    except (KeyError, IndexError, TypeError, AttributeError):
                        stueck = ""
                if stueck:
                    yield stueck.encode("utf-8")
    except urllib.error.HTTPError as e:
        koerper = ""
        try:
            koerper = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        yield f"\n⚠ Anbieter-Fehler {e.code}: {koerper}".encode("utf-8")
    except Exception as e:
        yield f"\n⚠ {str(e)[:300]}".encode("utf-8")


@app.post("/api/ai/chat")
async def ai_chat(mid: str = Form(...), nachrichten: str = Form("[]"), system: str = Form("")):
    """Chat-Anfrage an das konfigurierte Modell - Antwort als Text-Strom."""
    modell = _ki_modell(mid)
    try:
        msgs = json.loads(nachrichten)
        msgs = [m for m in msgs if isinstance(m, dict) and m.get("content")]
    except ValueError:
        raise HTTPException(400, "nachrichten muss JSON sein")
    if not modell.get("model"):
        raise HTTPException(400, "Dem Modell ist kein Anbieter-Modellname zugewiesen")
    from fastapi.responses import StreamingResponse
    return StreamingResponse(_ai_strom(modell, msgs, system),
                             media_type="text/plain; charset=utf-8")


@app.get("/api/fulltext/{did}")
def volltext(did: str):
    """Gesamttext des Dokuments mit Seitenmarkern (KI-Kontext, Zusammenfassen)."""
    d = _doc(did)
    teile = []
    for i in range(d.page_count):
        t = d[i].get_text().strip()
        if t:
            teile.append(f"--- Seite {i + 1} ---\n{t}")
    return {"text": "\n\n".join(teile), "seiten": d.page_count,
            "zeichen": sum(len(t) for t in teile)}


if __name__ == "__main__":
    import argparse
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8491)
    ap.add_argument("--file", default=None, help="PDF, das beim Start geöffnet wird")
    args = ap.parse_args()
    if args.file:
        try:
            _open(args.file)
        except Exception:
            pass
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
