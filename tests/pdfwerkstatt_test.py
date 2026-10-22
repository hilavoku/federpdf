# FederPDF-Testsuite: startet den gebauten Server und prueft die API
# end-to-end (Signaturen, Text, Formen, Markieren, OCR, KI, Bilder, Undo,
# Speichern, Druck). Sie erzeugt eigene Wegwerf-Signaturen und Fixtures —
# Nutzerdaten werden nie angefasst.
#
# Ausfuehrung:   py -3.14 tests/pdfwerkstatt_test.py
#   (erwartet die installierte App unter dem Standardpfad; abweichend:
#    PW_EXE=C:\Pfad\zu\FederPDFServer.exe py -3.14 tests/pdfwerkstatt_test.py)
# Benoetigt: requests, pymupdf, pillow  (pip install requests pymupdf pillow)
import os
import shutil
import subprocess
import tempfile
import time
import sys

import requests

EXE = os.environ.get("PW_EXE", r"C:\Anwendungen\FederPDF\server\FederPDFServer.exe")
DEMO = os.path.join(os.path.dirname(EXE), "demo", "demo.pdf")
PORT = 8515
BASE = f"http://127.0.0.1:{PORT}"
TMPD = tempfile.gettempdir()
FIXDIR = os.path.join(TMPD, "pw_test_fixtures")

failures = []


def check(name, cond, detail=""):
    print(("PASS" if cond else "FAIL") + f": {name}" + (f" [{detail}]" if detail and not cond else ""))
    if not cond:
        failures.append(name)


# Isolation: frisches Demo-Dokument erzwingen (alte User-Reste weg)
if os.path.isfile(DEMO):
    os.remove(DEMO)

srv = subprocess.Popen([EXE, "--port", str(PORT)], creationflags=subprocess.CREATE_NO_WINDOW)
try:
    for _ in range(60):
        time.sleep(0.5)
        try:
            if requests.get(BASE + "/api/health", timeout=2).json().get("ok"):
                break
        except Exception:
            pass
    else:
        print("FAIL: Server startet nicht")
        sys.exit(1)
    check("Server hochgefahren", True)

    # Über-Dialog (Klick auf Logo/FederPDF): Versions-Endpunkt + Logo-Route
    v = requests.get(BASE + "/api/version", timeout=5).json()
    check("Versions-Endpunkt", v.get("name") == "FederPDF" and len(v.get("version", "")) >= 5 and bool(v.get("pymupdf")), str(v))
    r = requests.get(BASE + "/logo.png", timeout=5)
    check("Logo fuer Über-Dialog", r.status_code == 200 and r.headers.get("content-type") == "image/png")

    d = requests.get(BASE + "/api/demo", timeout=15).json()
    did = d["id"]
    check("Demo offen", d["pages"] == 3 and len(d["toc"]) == 4)

    # Eigene Wegwerf-Signatur anlegen (Nutzer-Signaturen werden NIE angefasst)
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (300, 100), (20, 60, 160, 255)).save(buf, "PNG")
    r = requests.post(f"{BASE}/api/signature/upload",
                      files={"file": ("TestSig.png", buf.getvalue(), "image/png")},
                      data={"remove_bg": "0"}, timeout=10).json()
    check("Test-Signatur hochgeladen", r.get("ok"), str(r))
    ts1 = r["file"]

    sigs = requests.get(BASE + "/api/signatures", timeout=5).json()
    check("Signatur gelistet", any(s["file"] == ts1 for s in sigs), str(len(sigs)))

    # Signatur als Annotation (beweglich)
    r = requests.post(f"{BASE}/api/stamp/{did}", data={
        "page": "0", "x": "100", "y": "100", "width": "140", "fname": ts1}, timeout=10).json()
    check("Stempel-Annot angelegt", r.get("ok") and r.get("xref", 0) > 0, str(r))
    sig_xref = r.get("xref")
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    sig = next((a for a in annots if a["xref"] == sig_xref), None)
    check("Stempel gelistet als sign", sig is not None and sig["type"] == "sign", str(annots))
    r = requests.post(f"{BASE}/api/annot/move/{did}", data={
        "page": "0", "xref": str(sig_xref), "rect": "[300,200,440,260]"}, timeout=10).json()
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    sig2 = next((a for a in annots if a["xref"] == sig_xref), None)
    check("Stempel verschoben", r.get("ok") and sig2 and abs(sig2["rect"][0] - 300) < 1, str(sig2))

    # Signatur umbenennen -> Verweis in gesetzter Annotation muss mitziehen
    r = requests.post(f"{BASE}/api/signature/rename", data={
        "old": ts1, "new": "TestSig Umbenannt"}, timeout=10).json()
    check("Signatur umbenannt", r.get("ok") and r.get("file") == "TestSig Umbenannt.png", str(r))
    ts2 = r["file"]
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    sig3 = next((a for a in annots if a["xref"] == sig_xref), None)
    check("Stempel-Verweis mitumbenannt", sig3 and sig3.get("file") == ts2, str(sig3))

    # Signatur loeschen -> Verweis geleert (Platzhalter), Datei weg
    r = requests.post(f"{BASE}/api/signature/delete", data={"fname": ts2}, timeout=10).json()
    sigs_after = requests.get(f"{BASE}/api/signatures", timeout=5).json()
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    sig4 = next((a for a in annots if a["xref"] == sig_xref), None)
    check("Signatur geloescht + Verweis geleert",
          r.get("ok") and not any(s["file"] == ts2 for s in sigs_after)
          and sig4 and sig4.get("file") == "", str(sig4))

    # Freitext-Annotation mit Font/Stil/Groesse
    r = requests.post(f"{BASE}/api/annot/text/{did}", data={
        "page": "0", "rect": "[100,300,300,330]", "text": "Bemerkung in Fett",
        "size": "14", "font": "hebo", "color": "0.1,0.1,0.6"}, timeout=10).json()
    check("Freitext angelegt", r.get("ok") and r.get("xref", 0) > 0, str(r))
    txt_xref = r.get("xref")
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    txt = next((a for a in annots if a["xref"] == txt_xref), None)
    check("Freitext-Eigenschaften", txt and txt["font"] == "hebo" and txt["size"] == 14 and "Bemerkung" in txt["text"], str(txt))
    # Text aendern (re-create mit xref)
    r = requests.post(f"{BASE}/api/annot/text/{did}", data={
        "page": "0", "rect": "[100,300,300,330]", "text": "Geaendert kursiv",
        "size": "12", "font": "tiit", "color": "1,0,0", "xref": str(txt_xref)}, timeout=10).json()
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    txt2 = next((a for a in annots if a["xref"] == r.get("xref")), None)
    check("Freitext geaendert (neu erzeugt)", txt2 and "Geaendert" in txt2["text"] and txt2["font"] == "tiit", str(txt2))

    # Freitext verschieben - Position muss BLEIBEN (Regressionsbug: sprang zurueck)
    ft_xref = txt2["xref"]
    r = requests.post(f"{BASE}/api/annot/move/{did}", data={
        "page": "0", "xref": str(ft_xref), "rect": "[400,500,600,535]"}, timeout=10).json()
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    txt3 = next((a for a in annots if a["xref"] == ft_xref), None)
    check("Freitext verschoben und geblieben", r.get("ok") and txt3 and abs(txt3["rect"][0] - 400) < 1, str(txt3))

    # Formularfeld mit Rect (fuer Eingabe direkt aufs Papier)
    fields = requests.get(f"{BASE}/api/fields/{did}", timeout=10).json()
    vor = next((f for f in fields if f["name"] == "Vorname"), None)
    check("Feld mit Position", vor is not None and len(vor.get("rect", [])) == 4, str(vor))
    requests.post(f"{BASE}/api/field/{did}", data={"page": "2", "name": "Vorname", "value": "Guido"}, timeout=10)
    fields = requests.get(f"{BASE}/api/fields/{did}", timeout=10).json()
    check("Feld gesetzt", next((f for f in fields if f["name"] == "Vorname"), {}).get("value") == "Guido")

    # ---------- Rueckgaengig (vor dem Seitenloeschen: Formularfelder liegen auf Seite 3) ----------
    r = requests.post(f"{BASE}/api/annot/text/{did}", data={
        "page": "0", "rect": "[80,80,240,110]", "text": "UndoProbe", "size": "12",
        "font": "helv", "color": "0,0,0"}, timeout=10).json()
    ux = r["xref"]
    u = requests.post(f"{BASE}/api/undo/{did}", timeout=10).json()
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    check("Undo: Text entfernt", u.get("undone") and not any(a["xref"] == ux for a in annots), str(u))

    # Eigene Wegwerf-Signatur fuer Undo-Stempel
    buf = io.BytesIO()
    Image.new("RGBA", (300, 100), (160, 20, 60, 255)).save(buf, "PNG")
    r = requests.post(f"{BASE}/api/signature/upload",
                      files={"file": ("UndoSig.png", buf.getvalue(), "image/png")},
                      data={"remove_bg": "0"}, timeout=10).json()
    usig = r["file"]
    r = requests.post(f"{BASE}/api/stamp/{did}", data={
        "page": "0", "x": "500", "y": "600", "width": "120", "fname": usig}, timeout=10).json()
    s3 = r["xref"]
    orig = r["rect"]
    requests.post(f"{BASE}/api/annot/move/{did}", data={
        "page": "0", "xref": str(s3), "rect": "[50,50,190,110]"}, timeout=10)
    u = requests.post(f"{BASE}/api/undo/{did}", timeout=10).json()
    annots = requests.get(f"{BASE}/api/annots/{did}/0", timeout=10).json()
    s3b = next((a for a in annots if a["xref"] == s3), None)
    check("Undo: Verschieben zurueck", u.get("undone") and s3b and abs(s3b["rect"][0] - orig[0]) < 1, str(s3b))

    requests.post(f"{BASE}/api/field/{did}", data={"page": "2", "name": "Nachname", "value": "Temp"}, timeout=10)
    u = requests.post(f"{BASE}/api/undo/{did}", timeout=10).json()
    fields = requests.get(f"{BASE}/api/fields/{did}", timeout=10).json()
    nach = next((f for f in fields if f["name"] == "Nachname"), {})
    check("Undo: Feld zurueck", nach.get("value") == "", str(nach))

    # --- Speichern unter ---
    ziel = os.path.join(TMPD, "pw_test_saveas.pdf")
    if os.path.isfile(ziel):
        os.remove(ziel)
    r = requests.get(f"{BASE}/api/saveas/{did}", params={"path": ziel}, timeout=15)
    check("Speichern unter: Kopie erzeugt", r.ok and os.path.isfile(ziel) and os.path.getsize(ziel) > 1000,
          f"status={r.status_code}")
    curj = requests.get(f"{BASE}/api/current", timeout=5).json()
    check("Speichern unter: neue Datei ist Arbeitsdokument", curj.get("name") == "pw_test_saveas.pdf", str(curj.get("name")))
    ann_sofort = requests.get(f"{BASE}/api/annots/{did}/0", timeout=5).json()
    check("Speichern unter: Annotationen bleiben greifbar", any(a["type"] == "sign" for a in ann_sofort),
          str(len(ann_sofort)))

    # --- Passwortgeschtzte Signatur: verschluesselt gespeichert, stampbar ---
    buf2 = io.BytesIO()
    Image.new("RGBA", (200, 80), (160, 30, 30, 255)).save(buf2, "PNG")
    r = requests.post(f"{BASE}/api/signature/upload",
                      files={"file": ("PwSig.png", buf2.getvalue(), "image/png")},
                      data={"remove_bg": "0", "password": "geheim"}, timeout=10).json()
    pwfile = r.get("file", "")
    check("Geschuetzte Signatur als .pwdsig", r.get("ok") and pwfile.endswith(".pwdsig"), str(r))
    sigdir = os.path.join(os.path.dirname(EXE), "signatures")
    inhalt = open(os.path.join(sigdir, pwfile), "rb").read()
    check("Datei verschluesselt (kein Klartext-PNG)", b"\x89PNG" not in inhalt and b"token" in inhalt)
    r = requests.post(f"{BASE}/api/stamp/{did}", data={"page": "0", "x": "100", "y": "400",
                      "width": "120", "fname": pwfile}, timeout=10)
    check("Stempeln mit (frisch entsperrter) Pw-Sig", r.ok and r.json().get("xref", 0) > 0, str(r.status_code))
    pwx = r.json().get("xref")

    # --- Drehen 90 Grad + Undo ---
    an0 = next(a for a in requests.get(f"{BASE}/api/annots/{did}/0", timeout=5).json() if a["xref"] == pwx)
    r = requests.post(f"{BASE}/api/annot/rotate/{did}", data={"page": "0", "xref": str(pwx), "delta": "90"}, timeout=10)
    an1 = next((a for a in requests.get(f"{BASE}/api/annots/{did}/0", timeout=5).json() if a["xref"] == pwx), None)
    check("Signatur gedreht (Breite/Hoehe getauscht, rot=90)",
          r.ok and an1 and an1.get("rot") == 90 and abs((an1["rect"][3]-an1["rect"][1]) - (an0["rect"][2]-an0["rect"][0])) < 1,
          str(an1))
    u = requests.post(f"{BASE}/api/undo/{did}", timeout=10).json()
    an2 = next((a for a in requests.get(f"{BASE}/api/annots/{did}/0", timeout=5).json() if a["xref"] == pwx), None)
    check("Undo: Drehung zurueck", u.get("undone") and an2 and an2.get("rot") == 0, str(an2))

    # --- Freier Winkel (Zielwert) + gedrehtes Vorschaubild ---
    import math as _m
    r = requests.post(f"{BASE}/api/annot/rotate/{did}", data={"page": "0", "xref": str(pwx), "to": "37.5"}, timeout=10)
    an3 = next((a for a in requests.get(f"{BASE}/api/annots/{did}/0", timeout=5).json() if a["xref"] == pwx), None)
    # erwartete Huelle: Bild 200x80 um 37.5 Grad -> (200*c+80*s, 200*s+80*c)
    c, s = _m.cos(_m.radians(37.5)), _m.sin(_m.radians(37.5))
    erw = (200 * c + 80 * s) / (200 * s + 80 * c)      # Breite/Hoehe-Verhaeltnis
    ist = (an3["rect"][2] - an3["rect"][0]) / (an3["rect"][3] - an3["rect"][1]) if an3 else 0
    check("Freier Winkel 37.5 (rot + Huellen-Verhaeltnis)",
          r.ok and an3 and abs(an3["rot"] - 37.5) < 0.01 and abs(ist - erw) < 0.05, f"rot={an3 and an3['rot']} vh={ist:.2f}/{erw:.2f}")
    r = requests.get(f"{BASE}/api/signature/file/PwSig.pwdsig?rot=37.5", timeout=10)
    check("Gedrehtes Vorschaubild lieferbar", r.ok and r.content[:4] == b"\x89PNG", str(r.status_code))
    u = requests.post(f"{BASE}/api/undo/{did}", timeout=10).json()
    an4 = next((a for a in requests.get(f"{BASE}/api/annots/{did}/0", timeout=5).json() if a["xref"] == pwx), None)
    check("Undo: freier Winkel zurueck", u.get("undone") and an4 and an4.get("rot") == 0, str(an4 and an4.get("rot")))

    # --- Einbrennen (flatten): Annotationen weg, Formularfelder bleiben ---
    r = requests.post(f"{BASE}/api/save/{did}?flatten=1", timeout=20).json()
    check("Einbrennen-Speichern ok", r.get("ok") and r.get("flattened"), str(r))
    annots_flach = requests.get(f"{BASE}/api/annots/{did}/0", timeout=5).json()
    check("Nach Einbrennen keine beweglichen Objekte", not annots_flach, str(len(annots_flach)))
    flds = requests.get(f"{BASE}/api/fields/{did}", timeout=5).json()
    check("Formularfelder ueberleben Einbrennen", any(f["name"] == "Vorname" for f in flds), str(len(flds)))

    # --- Speichern unter MIT Einbrennen ---
    ziel2 = os.path.join(TMPD, "pw_test_saveas_burn.pdf")
    if os.path.isfile(ziel2):
        os.remove(ziel2)
    r = requests.post(f"{BASE}/api/stamp/{did}", data={"page": "0", "x": "150", "y": "500",
                      "width": "100", "fname": pwfile}, timeout=10)
    check("Stempel vor Speichern-unter gesetzt", r.ok, str(r.status_code))
    r = requests.get(f"{BASE}/api/saveas/{did}", params={"path": ziel2, "flatten": 1}, timeout=20).json()
    check("Speichern unter mit Einbrennen", r.get("ok") and r.get("flattened") and os.path.isfile(ziel2), str(r))
    check("Speichern-unter-Einbrennen: keine beweglichen Objekte",
          not requests.get(f"{BASE}/api/annots/{did}/0", timeout=5).json())

    # --- Originaltext editieren (echter Text, kein Bild) ---
    import json as _json
    alter = "FederPDF Demo-Dokument"
    zeilen0 = requests.get(f"{BASE}/api/text/{did}/0", timeout=5).json()["lines"]
    zeile = next((l for l in zeilen0 if alter in l["t"]), None)
    r = requests.get(f"{BASE}/api/textspan/{did}/0",
                     params={"x0": zeile["x0"], "y0": zeile["y0"], "x1": zeile["x1"], "y1": zeile["y1"]},
                     timeout=5).json()
    check("Textspanne erkannt (Groesse/Farbe)", abs(r.get("size", 0) - 18) < 3 and r.get("color") == [0, 0, 0], str(r))
    r = requests.post(f"{BASE}/api/text/replace/{did}", data={
        "page": "0", "rect": _json.dumps([zeile["x0"], zeile["y0"], zeile["x1"], zeile["y1"]]),
        "text": "FederPDF Demo GEANDERT"}, timeout=15)
    check("Originaltext ersetzt", r.ok and r.json().get("size", 0) > 10, str(r.status_code))
    t0 = requests.get(f"{BASE}/api/text/{did}/0", timeout=5).json()["lines"]
    check("Neuer Text im Seiteninhalt", any("GEANDERT" in l["t"] for l in t0), str(t0[:2]))
    check("Alter Text weg", not any(alter in l["t"] for l in t0))
    u = requests.post(f"{BASE}/api/undo/{did}", timeout=15).json()
    t0 = requests.get(f"{BASE}/api/text/{did}/0", timeout=5).json()["lines"]
    check("Undo: Originaltext zurueck",
          u.get("undone") and any(alter in l["t"] for l in t0) and not any("GEANDERT" in l["t"] for l in t0))

    # Seite loeschen
    r = requests.post(f"{BASE}/api/deletepage/{did}", data={"page": "2"}, timeout=10).json()
    check("Seite geloescht", r.get("ok") and r.get("pages") == 2, str(r))

    # Druckansicht (enthaelt eingebettete Seitenbilder)
    pr = requests.get(f"{BASE}/api/print/{did}", timeout=60)
    check("Druckansicht erzeugt", pr.status_code == 200 and "data:image/png;base64" in pr.text)

    save = requests.post(f"{BASE}/api/save/{did}", timeout=15).json()
    check("Speichern", save.get("ok", False))

    # ---------- v0.18: Markierungen, Formen, OCR, KI, Dokument-Schriften ----------
    # Frisches Demo als eigenes Arbeitsdokument: die v0.18-Checks duerfen den
    # obigen Ablauf (Drehen, Einbrennen, Ersetzen) nicht beeinflussen und umgekehrt.
    vdid = requests.get(BASE + "/api/demo", timeout=15).json()["id"]
    # Woerter-Quads: duennes waagerechtes Band genau auf die Zeilenmitte gelegt
    t0 = requests.get(f"{BASE}/api/text/{vdid}/0", timeout=10).json()
    zl = next((l for l in t0["lines"] if "Markiere mich" in l["t"]), None)
    ym = round((zl["y0"] + zl["y1"]) / 2, 1) if zl else 116.0
    q = requests.get(f"{BASE}/api/textquads/{vdid}/0",
                     params={"x0": 70, "y0": ym, "x1": 300, "y1": ym + 0.3}, timeout=10).json()
    check("Textquads: duennes Band erfasst Woerter", len(q.get("quads", [])) >= 3 and "Markiere" in q.get("text", ""), str(q)[:90])
    quads = str(q["quads"])
    r = requests.post(f"{BASE}/api/annot/markup/{vdid}", data={
        "page": "0", "art": "h", "quads": quads, "farbe": "FFD300",
        "deckkraft": "45", "staerke": "1"}, timeout=10).json()
    mk_x = r.get("xref", 0)
    check("Marker angelegt", r.get("ok") and mk_x > 0, str(r))
    r = requests.post(f"{BASE}/api/annot/markup/{vdid}", data={
        "page": "0", "art": "u", "quads": quads, "farbe": "0000FF",
        "deckkraft": "100", "staerke": "2.5"}, timeout=10).json()
    un_x = r.get("xref", 0)
    check("Unterstreichen angelegt", r.get("ok") and un_x > 0, str(r))
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    subs = sorted(a["sub"] for a in annots if a["type"] == "markup")
    check("Markierungen gelistet (h+u)", subs == ["h", "u"], str(subs))
    mke = next((a for a in annots if a.get("xref") == mk_x), {})
    check("Marker-Stil lesbar", mke.get("farbe") == "FFD300" and abs(mke.get("deckkraft", 0) - 45) < 1, str(mke)[:90])

    # Formen: Rechteck, Pfeil, Tinte
    r = requests.post(f"{BASE}/api/annot/shape/{vdid}", data={
        "page": "0", "typ": "rect", "rect": "[100,380,220,440]", "punkte": "[]",
        "breite": "2.5", "farbe": "E0242F", "fuellung": "FFFF00", "deckkraft": "100"}, timeout=10).json()
    rect_x = r.get("xref", 0)
    check("Rechteck angelegt", r.get("ok") and rect_x > 0, str(r))
    r = requests.post(f"{BASE}/api/annot/shape/{vdid}", data={
        "page": "0", "typ": "arrow", "rect": "[0,0,0,0]", "punkte": "[[100,470],[260,500]]",
        "breite": "2", "farbe": "0B6EC9"}, timeout=10).json()
    arr_x = r.get("xref", 0)
    check("Pfeil angelegt", r.get("ok") and arr_x > 0, str(r))
    r = requests.post(f"{BASE}/api/annot/shape/{vdid}", data={
        "page": "0", "typ": "ink", "rect": "[0,0,0,0]",
        "punkte": "[[[100,560],[140,575],[180,550]]]", "breite": "3", "farbe": "000000"}, timeout=10).json()
    ink_x = r.get("xref", 0)
    check("Tinte angelegt", r.get("ok") and ink_x > 0, str(r))
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    fsubs = sorted(a["sub"] for a in annots if a["type"] == "shape")
    check("Formen gelistet (rect/arrow/ink)", fsubs == ["arrow", "ink", "rect"], str(fsubs))

    # Form verschieben+skalieren (shapemove)
    alt_rect = next(a["rect"] for a in annots if a.get("xref") == rect_x)
    neu_rect = [alt_rect[0] + 40, alt_rect[1] + 30, alt_rect[2] + 60, alt_rect[3] + 40]
    r = requests.post(f"{BASE}/api/annot/shapemove/{vdid}", data={
        "page": "0", "xref": str(rect_x), "alt": str(alt_rect), "neu": str(neu_rect)}, timeout=10).json()
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    neu_gelesen = next((a["rect"] for a in annots if a.get("xref") == rect_x), None)
    check("Form verschoben+skaliert", r.get("ok") and neu_gelesen and abs(neu_gelesen[0] - neu_rect[0]) < 1.5,
          f"{neu_gelesen}")
    # Pfeil: Move synkt NM-Punkte, Flip (gespiegelter Zug) + Undo, gefuellte Spitze (/IC)
    arr_alt = next(a["rect"] for a in annots if a.get("xref") == arr_x)
    arr_punkte_vor = next(a["punkte"] for a in annots if a.get("xref") == arr_x)
    arr_neu = [arr_alt[0] + 25, arr_alt[1] + 20, arr_alt[2] + 25, arr_alt[3] + 20]   # reine Verschiebung
    requests.post(f"{BASE}/api/annot/shapemove/{vdid}", data={
        "page": "0", "xref": str(arr_x), "alt": str(arr_alt), "neu": str(arr_neu)}, timeout=10)
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    arr_np = next((a["punkte"] for a in annots if a.get("xref") == arr_x), None)
    check("Pfeil-Move: NM-Punkte nachgezogen", arr_np and abs(arr_np[0][0] - (arr_punkte_vor[0][0] + 25)) < 1.5, str(arr_np))
    flip_neu = [arr_neu[2] - 20, arr_neu[3] - 20, arr_neu[0] + 20, arr_neu[1] + 20]   # gespiegelt: x1<x0, y1<y0
    requests.post(f"{BASE}/api/annot/shapemove/{vdid}", data={
        "page": "0", "xref": str(arr_x), "alt": str(arr_neu), "neu": str(flip_neu)}, timeout=10)
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    arr_fp = next((a["punkte"] for a in annots if a.get("xref") == arr_x), None)
    check("Pfeil-Flip: Spitze folgt dem Griff", bool(arr_fp) and arr_fp[1][0] < arr_fp[0][0] and arr_fp[1][1] < arr_fp[0][1], str(arr_fp))
    requests.post(f"{BASE}/api/undo/{vdid}", timeout=10)
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    arr_up = next((a for a in annots if a.get("xref") == arr_x), None)
    check("Pfeil-Flip-Undo: Punkte zurueck, Rect normal",
          bool(arr_up) and abs(arr_up["punkte"][1][0] - arr_np[1][0]) < 1 and abs(arr_up["punkte"][1][1] - arr_np[1][1]) < 1
          and arr_up["rect"][2] > arr_up["rect"][0], str(arr_up)[:120])
    pdf_bytes = requests.get(f"{BASE}/api/download/{vdid}", timeout=15).content
    check("Pfeilspitze gefuellt im PDF (/LE + /IC)", b"/ClosedArrow" in pdf_bytes and b"/IC" in pdf_bytes)
    # Stil aendern
    r = requests.post(f"{BASE}/api/annot/style/{vdid}", data={
        "page": "0", "xref": str(rect_x), "farbe": "00AA00", "breite": "4"}, timeout=10).json()
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    gestylt = next((a for a in annots if a.get("xref") == rect_x), {})
    check("Form-Stil geaendert", r.get("ok") and gestylt.get("farbe") == "00AA00" and abs(gestylt.get("breite", 0) - 4) < 0.1, str(gestylt)[:90])
    # Loeschen + Undo legt wieder an
    requests.post(f"{BASE}/api/annot/delete/{vdid}", data={"page": "0", "xref": str(ink_x)}, timeout=10)
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    check("Tinte geloescht", not any(a.get("xref") == ink_x for a in annots))
    u = requests.post(f"{BASE}/api/undo/{vdid}", timeout=10).json()
    annots = requests.get(f"{BASE}/api/annots/{vdid}/0", timeout=10).json()
    check("Undo: Tinte wieder da", u.get("undone") and any(a["type"] == "shape" and a["sub"] == "ink" for a in annots))

    # OCR: Scan-PDF (Bildseite ohne Text) oeffnen, erkennen, durchsuchbar machen.
    # Fixtures erzeugt der Test selbst: Bildseite (fuer OCR) + Arial eingebettet.
    import pymupdf
    from PIL import ImageDraw, ImageFont
    os.makedirs(FIXDIR, exist_ok=True)
    scan_pfad = os.path.join(FIXDIR, "pw_test_scan.pdf")
    img = Image.new("RGB", (1240, 1754), "white")
    dr = ImageDraw.Draw(img)
    try:
        fnt = ImageFont.truetype("arial.ttf", 52)
    except Exception:
        fnt = ImageFont.load_default()
    for i in range(12):
        dr.text((100, 120 + i * 110), f"Beispieltext Zeile {i + 1}", fill="black", font=fnt)
    img_pfad = os.path.join(FIXDIR, "pw_test_scan.png")
    img.save(img_pfad)
    sdoc = pymupdf.open()
    spg = sdoc.new_page(width=595, height=842)
    spg.insert_image(spg.rect, filename=img_pfad)
    sdoc.save(scan_pfad)
    scan = requests.get(BASE + "/api/open",
                        params={"q": scan_pfad}, timeout=20).json()
    sdid = scan["id"]
    oi = requests.get(f"{BASE}/api/ocr/info/{sdid}", timeout=10).json()
    check("OCR-Info: Scan ohne Text", oi.get("seiten_ohne_text") == [0] and "deu" in oi.get("tessdata", []), str(oi)[:90])
    r = requests.post(f"{BASE}/api/ocr/{sdid}", data={"page": "0", "lang": "deu+eng", "dpi": "300"}, timeout=120).json()
    check("OCR-Seite ausgefuehrt", r.get("ok") and not r.get("skip") and r.get("zeilen", 0) >= 10, str(r))
    s = requests.get(f"{BASE}/api/search/{sdid}", params={"q": "Beispieltext"}, timeout=10).json()
    check("OCR: Scan danach durchsuchbar", len(s.get("hits", [])) >= 5, str(len(s.get("hits", []))))
    r = requests.post(f"{BASE}/api/ocr/{sdid}", data={"page": "0", "lang": "deu+eng"}, timeout=30).json()
    check("OCR: Seite mit Text wird uebersprungen", r.get("ok") and r.get("skip"), str(r))

    # KI-Endpunkte: Validierung ohne Konfiguration
    r = requests.get(f"{BASE}/api/ai/models", params={"url": "", "key": "", "art": "openai"}, timeout=10)
    check("KI-Modelle: leere URL abgewiesen", r.status_code in (400, 502), str(r.status_code))
    r = requests.post(f"{BASE}/api/ai/chat", data={"mid": "gibtsnicht", "nachrichten": "[]"}, timeout=10)
    check("KI-Chat: unbekanntes Modell 404", r.status_code == 404, str(r.status_code))
    ft = requests.get(f"{BASE}/api/fulltext/{vdid}", timeout=10).json()
    check("Volltext mit Seitenmarkern", ft.get("zeichen", 0) > 100 and "--- Seite 1 ---" in ft.get("text", ""), str(ft.get("zeichen")))

    # Dokument-Schriften: Font-PDF mit eingebettetem Arial (Fixtures s.o.)
    font_pfad = os.path.join(FIXDIR, "pw_test_font.pdf")
    fdoc = pymupdf.open()
    fpg = fdoc.new_page(width=595, height=842)
    fpg.insert_font(fontname="Arial", fontfile=r"C:\Windows\Fonts\arial.ttf")
    fpg.insert_text((72, 100), "Schriftprobe mit eingebettetem Arial", fontname="Arial", fontsize=14)
    fpg.insert_text((72, 130), "Zweite Zeile fuer die Schriftprobe", fontname="Arial", fontsize=12)
    fdoc.save(font_pfad)
    fdok = requests.get(BASE + "/api/open",
                        params={"q": font_pfad}, timeout=20).json()
    fid = fdok["id"]
    fonts = requests.get(f"{BASE}/api/fonts/{fid}", timeout=10).json()
    arial = next((f for f in fonts if "Arial" in f.get("basefont", "") and f.get("nutzbar")), None)
    check("Eingebettete Schrift erkannt (Arial)", arial is not None, str(fonts)[:90])
    if arial:
        fr = requests.get(f"{BASE}/api/font/file/{fid}/{arial['xref']}", timeout=10)
        check("Schrift extrahierbar", fr.ok and len(fr.content) > 10000, f"{len(fr.content)} Bytes")
        kodierung = f"doc~{arial['xref']}~{arial['basefont']}"
        r = requests.post(f"{BASE}/api/annot/text/{fid}", data={
            "page": "0", "rect": "[100,200,330,230]", "text": "Arial Schriftprobe",
            "size": "14", "font": kodierung, "color": "0,0,0"}, timeout=10).json()
        annots = requests.get(f"{BASE}/api/annots/{fid}/0", timeout=10).json()
        tfa = next((a for a in annots if a["type"] == "text"), {})
        check("Text in Dokument-Schrift", r.get("ok") and tfa.get("font") == kodierung, str(tfa)[:90])

    # Original-Text loeschen (Redaction)
    lines1 = requests.get(f"{BASE}/api/text/{did}/1", timeout=10).json()["lines"]
    ziel = lines1[0]
    rects = [[round(ziel["x0"], 1), round(ziel["y0"], 1), round(ziel["x1"], 1), round(ziel["y1"], 1)]]
    r = requests.post(f"{BASE}/api/delete/{did}", data={"page": "1", "rects": str(rects)}, timeout=10).json()
    lines1b = requests.get(f"{BASE}/api/text/{did}/1", timeout=10).json()["lines"]
    check("Original-Text geloescht", r.get("ok") and not any(l["t"] == ziel["t"] for l in lines1b))

    # Suche
    s = requests.get(f"{BASE}/api/search/{did}", params={"q": "Beispieltext"}, timeout=10).json()
    check("Suche findet Treffer", len(s.get("hits", [])) >= 10, str(len(s.get("hits", []))))

    # Seite drehen (Rendermass soll getauscht werden)
    png_before = requests.get(f"{BASE}/api/page/{did}/0", timeout=15).content
    w_before = int.from_bytes(png_before[16:20], "big")
    h_before = int.from_bytes(png_before[20:24], "big")
    r = requests.post(f"{BASE}/api/rotate/{did}", data={"page": "0", "delta": "90"}, timeout=10).json()
    png_after = requests.get(f"{BASE}/api/page/{did}/0", timeout=15).content
    w_after = int.from_bytes(png_after[16:20], "big")
    h_after = int.from_bytes(png_after[20:24], "big")
    check("Seite gedreht (Format getauscht)", r.get("ok") and (w_before - h_before) * (w_after - h_after) < 0,
          f"{w_before}x{h_before} -> {w_after}x{h_after}")

    # --- Eingebettete Bilder: Skalieren + Drehen (v0.19.1) ---
    import pymupdf
    tdoc = pymupdf.open()
    tpg = tdoc.new_page(width=595, height=842)
    tpg.insert_text((72, 90), "Bildtest", fontsize=14)
    ibuf = io.BytesIO()
    Image.new("RGBA", (200, 140), (200, 30, 30, 255)).save(ibuf, "PNG")
    tpg.insert_image(pymupdf.Rect(80, 120, 280, 260), stream=ibuf.getvalue())
    tb = io.BytesIO()
    tdoc.save(tb)
    r = requests.post(f"{BASE}/api/upload", files={"file": ("pw_bild_test.pdf", tb.getvalue(), "application/pdf")},
                      timeout=15).json()
    check("Bild-Test-PDF hochgeladen", r.get("id"), str(r))
    bid = r["id"]
    ii = requests.get(f"{BASE}/api/imageinfo/{bid}/0", timeout=10).json()
    bild0 = ii["bilder"][0]
    check("Bildinfo: Platzierung+xref", bild0["bbox"] == [80.0, 120.0, 280.0, 260.0] and bild0["xref"] > 0, str(ii))
    r = requests.get(f"{BASE}/api/image/file/{bid}/0/{bild0['xref']}", timeout=10)
    check("Bildbytes: PNG mit Alpha", r.status_code == 200 and r.content[:4] == b"\x89PNG", str(r.status_code))
    r = requests.post(f"{BASE}/api/image/move/{bid}", data={
        "page": "0", "xref": str(bild0["xref"]), "alt": "[80,120,280,260]", "neu": "[80,120,180,190]"},
        timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{bid}/0", timeout=10).json()
    check("Bild skaliert (100x70)", r.get("ok") and ii["bilder"][-1]["bbox"] == [80.0, 120.0, 180.0, 190.0],
          str(ii["bilder"][-1]))
    r = requests.post(f"{BASE}/api/image/rotate/{bid}", data={
        "page": "0", "xref": str(bild0["xref"]), "alt": "[80,120,180,190]", "winkel": "90"}, timeout=10).json()
    check("Bild gedreht: Ruegabe-Rect (Huelle 100x70 -> 70x100 um Mitte 130,155)", r.get("ok") and r.get("rect") == [95.0, 105.0, 165.0, 205.0], str(r))
    ii = requests.get(f"{BASE}/api/imageinfo/{bid}/0", timeout=10).json()
    check("Bild gedreht: Huelle in der Sitzung", ii["bilder"][-1]["bbox"] == [95.0, 105.0, 165.0, 205.0],
          str(ii["bilder"][-1]))
    u = requests.post(f"{BASE}/api/undo/{bid}", timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{bid}/0", timeout=10).json()
    check("Undo: Rotation zurueck", u.get("undone") and ii["bilder"][-1]["bbox"] == [80.0, 120.0, 180.0, 190.0],
          str(ii["bilder"][-1]))
    u = requests.post(f"{BASE}/api/undo/{bid}", timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{bid}/0", timeout=10).json()
    check("Undo: Skalierung zurueck", u.get("undone") and ii["bilder"][-1]["bbox"] == [80.0, 120.0, 280.0, 260.0],
          str(ii["bilder"][-1]))
    # Datei-Level-Beweis: 30° drehen, speichern, frisch oeffnen (Huelle 243.2x221.2 um 180,190)
    r = requests.post(f"{BASE}/api/image/rotate/{bid}", data={
        "page": "0", "xref": str(bild0["xref"]), "alt": "[80,120,280,260]", "winkel": "30"}, timeout=10).json()
    check("Bild um 30 Grad gedreht", r.get("ok") and abs(r["rect"][0] - 58.4) < 1.5, str(r))
    bild_ziel = os.path.join(TMPD, "pw_test_bild.pdf")
    if os.path.isfile(bild_ziel):
        os.remove(bild_ziel)
    r = requests.get(f"{BASE}/api/saveas/{bid}", params={"path": bild_ziel}, timeout=15)
    check("Bild-PDF gesichert", r.ok and os.path.isfile(bild_ziel), str(r.status_code))
    frisch = pymupdf.open(bild_ziel)
    platz = [i["bbox"] for i in frisch[0].get_image_info(xrefs=True)]
    huelle = [round(v, 1) for v in [58.4, 79.4, 301.6, 300.6]]
    check("Datei-Level: 30-Grad-Huelle gespeichert",
          any(all(abs(a - b) < 1.2 for a, b in zip(p, huelle)) for p in platz), str(platz))
    frisch.close()

    # ---------- v0.21.12: Bild-Geister bei ImageMask-Briefkoepfen (Nutzer-Fund) ----------
    # Briefkopflogos bestehen oft aus gestapelten 1-bit-ImageMask-Bildern ("ING"
    # + Loewe). get_bboxlog meldet sie als "fill-imgmask" - zaehlte der Geister-
    # Filter nur "fill-image", divergierte die Zaehlung gegen get_image_info und
    # das Sicherheitsnetz schaltete ihn KOMPLETT ab: der weiss ueberdeckte Geist
    # blieb greifbar, jeder Zug erzeugte eine sichtbare Kopie (Loewe weg, ING
    # haufenweise). Der Raw-Fixture geht bewusst an PyMuPDF vorbei (insert_image
    # erzeugt nie ImageMask-Objekte).
    import io
    import json

    def _masken_pdf():
        def roh_xobj(daten):
            return (b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ImageMask true "
                    b"/BitsPerComponent 1 /Length " + str(len(daten)).encode() + b" >>\nstream\n"
                    + daten + b"\nendstream")
        inhalt = (b"q 0 0 0 rg 200 0 0 140 80 582 cm /MA0 Do Q\n"
                  b"q 0 0 0 rg 200 0 0 140 80 582 cm /MA1 Do Q")
        objekte = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /XObject << /MA0 5 0 R /MA1 6 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
            roh_xobj(bytes([0b10101010] * 8)),
            roh_xobj(bytes([0b01010101] * 8)),
        ]
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%pw\n")
        offs = []
        for i, o in enumerate(objekte, start=1):
            offs.append(out.tell())
            out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
        xp = out.tell()
        out.write(f"xref\n0 {len(objekte)+1}\n".encode() + b"0000000000 65535 f \n")
        for off in offs:
            out.write(f"{off:010d} 00000 n \n".encode())
        out.write(f"trailer\n<< /Size {len(objekte)+1} /Root 1 0 R >>\nstartxref\n{xp}\n%%EOF".encode())
        return out.getvalue()

    r = requests.post(f"{BASE}/api/upload", files={"file": ("pw_masken_test.pdf", _masken_pdf(), "application/pdf")},
                      timeout=15).json()
    check("Masken-PDF hochgeladen", r.get("id"), str(r))
    mid = r["id"]
    ii = requests.get(f"{BASE}/api/imageinfo/{mid}/0", timeout=10).json()
    check("Masken-Stapel: 2 Ebenen am selben Ort",
          len(ii["bilder"]) == 2 and ii["bilder"][0]["bbox"] == ii["bilder"][1]["bbox"] == [80.0, 120.0, 280.0, 260.0]
          and all(b["xref"] > 0 for b in ii["bilder"]), str(ii))
    ma, mb_ = ii["bilder"][0]["xref"], ii["bilder"][1]["xref"]
    r = requests.post(f"{BASE}/api/image/move/{mid}", data={
        "page": "0", "xref": str(ma), "xrefs": json.dumps([ma, mb_]),
        "alt": "[80,120,280,260]", "neu": "[300,150,500,290]"}, timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{mid}/0", timeout=10).json()
    check("Ebenen-Zug: alte Stelle geisterfrei (fill-imgmask gezaehlt)",
          r.get("ok") and len(ii["bilder"]) == 2
          and all(b["bbox"] == [300.0, 150.0, 500.0, 290.0] for b in ii["bilder"]), str(ii["bilder"]))
    u = requests.post(f"{BASE}/api/undo/{mid}", timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{mid}/0", timeout=10).json()
    check("Undo: Ebenen zurueck, Zielstelle geisterfrei",
          u.get("undone") and len(ii["bilder"]) == 2
          and all(b["bbox"] == [80.0, 120.0, 280.0, 260.0] for b in ii["bilder"]), str(ii["bilder"]))

    # ---------- v0.21.13: Masken-FARBEN + Hintergrund-Deckel (Nutzer-Fund) ----------
    # ImageMask-Bilder haben keine eigene Farbe - sie werden in der Fuellfarbe
    # des Content-Streams gemalt. Das Verschieben setzte sie farblos (schwarz)
    # wieder ein: das ING-Logo wurde s/w. Und auf farbigem Hintergrund hinterlies
    # der Weissdeckel einen weissen Fleck. Jetzt: Farb-Scan vor dem Do, Deckel in
    # gemessener Hintergrundfarbe, Verweigerung bei ungleichmaessigem Grund.
    from PIL import Image as _PILImage

    def _dunkel(did_, x0, y0, x1, y1):
        """Dunkelstes Pixel in der Region (Beweis: Text-Tinte sichtbar)."""
        png = requests.get(f"{BASE}/api/page/{did_}/0", timeout=15).content
        im = _PILImage.open(io.BytesIO(png)).convert("RGB")
        box = (int(x0 / 595 * im.width), int(y0 / 842 * im.height),
               int(x1 / 595 * im.width), int(y1 / 842 * im.height))
        klein = 255
        for px in im.crop(box).getdata():
            klein = min(klein, min(px))
        return klein

    def _farb_masken_pdf():
        def roh_xobj(daten):
            return (b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ImageMask true "
                    b"/BitsPerComponent 1 /Length " + str(len(daten)).encode() + b" >>\nstream\n"
                    + daten + b"\nendstream")
        # ImageMask: Sample 0 = malen. MA0 obere Haelfte (rot), MA1 untere (blau).
        ma0 = bytes([0x00] * 4 + [0xFF] * 4)
        ma1 = bytes([0xFF] * 4 + [0x00] * 4)
        inhalt = (b"q 1 1 0 rg 0 0 595 842 re f Q\n"          # gelber Hintergrund
                  b"q 1 0 0 rg 200 0 0 140 80 582 cm /MA0 Do Q\n"
                  b"q 0 0 1 rg 200 0 0 140 80 582 cm /MA1 Do Q")
        objekte = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /XObject << /MA0 5 0 R /MA1 6 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
            roh_xobj(ma0), roh_xobj(ma1),
        ]
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%pw\n")
        offs = []
        for i, o in enumerate(objekte, start=1):
            offs.append(out.tell())
            out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
        xp = out.tell()
        out.write(f"xref\n0 {len(objekte)+1}\n".encode() + b"0000000000 65535 f \n")
        for off in offs:
            out.write(f"{off:010d} 00000 n \n".encode())
        out.write(f"trailer\n<< /Size {len(objekte)+1} /Root 1 0 R >>\nstartxref\n{xp}\n%%EOF".encode())
        return out.getvalue()

    def _pixel(did_, x, y, toleranz=40):
        png = requests.get(f"{BASE}/api/page/{did_}/0", timeout=15).content
        im = _PILImage.open(io.BytesIO(png)).convert("RGB")
        px, py = int(x / 595 * im.width), int(y / 842 * im.height)
        nahe = [im.getpixel((max(0, min(im.width - 1, px + dx)), max(0, min(im.height - 1, py + dy))))
                for dx in (-2, 0, 2) for dy in (-2, 0, 2)]
        ziel = nahe[4]
        ok_ = all(all(abs(a - b) <= toleranz for a, b in zip(p, ziel)) for p in nahe)
        return ziel, ok_

    r = requests.post(f"{BASE}/api/upload", files={"file": ("pw_farb_masken.pdf", _farb_masken_pdf(), "application/pdf")},
                      timeout=15).json()
    check("Farb-Masken-PDF hochgeladen", r.get("id"), str(r))
    fid = r["id"]
    ii = requests.get(f"{BASE}/api/imageinfo/{fid}/0", timeout=10).json()
    check("Farb-Masken-Stapel erkannt",
          len(ii["bilder"]) == 2 and ii["bilder"][0]["bbox"] == ii["bilder"][1]["bbox"], str(ii))
    check("Tintenrahmen: obere Haelfte eng gemessen (v0.21.19)",
          ii["bilder"][0].get("ink") == [80.0, 120.0, 280.0, 190.0], str(ii["bilder"][0]))
    fa, fb_ = ii["bilder"][0]["xref"], ii["bilder"][1]["xref"]
    r = requests.post(f"{BASE}/api/image/move/{fid}", data={
        "page": "0", "xref": str(fa), "xrefs": json.dumps([fa, fb_]),
        "alt": "[80,120,280,260]", "neu": "[300,150,500,290]"}, timeout=15).json()
    check("Farb-Zug ok", r.get("ok"), str(r))
    ii = requests.get(f"{BASE}/api/imageinfo/{fid}/0", timeout=10).json()
    check("Farb-Deckel: alte Stelle geisterfrei (beliebige Deckfarbe)",
          len(ii["bilder"]) == 2 and all(b["bbox"] == [300.0, 150.0, 500.0, 290.0] for b in ii["bilder"]),
          str(ii["bilder"]))
    p1, o1 = _pixel(fid, 180, 190)      # alte Stelle: jetzt gelber Deckel
    check("Alte Stelle in Hintergrundfarbe (gelb)", o1 and p1[0] > 180 and p1[1] > 180 and p1[2] < 90, str(p1))
    p2, o2 = _pixel(fid, 400, 185)      # neue Stelle oben: rote Maske
    check("Maske oben bleibt rot", o2 and p2[0] > 180 and p2[1] < 90 and p2[2] < 90, str(p2))
    p3, o3 = _pixel(fid, 400, 255)      # neue Stelle unten: blaue Maske
    check("Maske unten bleibt blau", o3 and p3[2] > 180 and p3[0] < 90 and p3[1] < 90, str(p3))
    u = requests.post(f"{BASE}/api/undo/{fid}", timeout=10).json()
    p4, o4 = _pixel(fid, 180, 155)      # nach Undo: oben wieder rot am alten Ort
    p5, o5 = _pixel(fid, 180, 225)      # nach Undo: unten wieder blau
    p6, o6 = _pixel(fid, 400, 220)      # Zielstelle: gelber Deckel vom Undo
    check("Undo: Farben am alten Ort, Zielstelle hintergrundfarben",
          u.get("undone") and o4 and p4[0] > 180 and p4[1] < 90
          and o5 and p5[2] > 180 and o6 and p6[0] > 180 and p6[2] < 90, f"{p4}/{p5}/{p6}")
    # v0.21.20: Tintenrahmen ueberlebt Drehungen (Matrix-Ecken-Transformation) -
    # vorher sprang der Rahmen bei gedrehter Platzierung auf die Vollflaeche.
    # 90° im Uhrzeigersinn: obere Haelfte (Tinte) wandert auf die rechte Haelfte.
    r = requests.post(f"{BASE}/api/image/rotate/{fid}", data={
        "page": "0", "xref": str(fa), "xrefs": json.dumps([fa, fb_]),
        "alt": "[80,120,280,260]", "winkel": "90"}, timeout=15).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{fid}/0", timeout=10).json()
    check("Tintenrahmen nach 90°-Drehung (Tinte = rechte Haelfte)",
          r.get("ok") and r.get("rect") == [110.0, 90.0, 250.0, 290.0]
          and ii["bilder"][0].get("ink") == [180.0, 90.0, 250.0, 290.0], str(ii["bilder"][0]))
    u = requests.post(f"{BASE}/api/undo/{fid}", timeout=10).json()

    def _streifen_pdf():
        # gelber Streifen nur links (bis x=300), Maske schlingert darueber ->
        # Hintergrund ungleichmaessig -> Zug muss verweigert werden
        def roh_xobj(daten):
            return (b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ImageMask true "
                    b"/BitsPerComponent 1 /Length " + str(len(daten)).encode() + b" >>\nstream\n"
                    + daten + b"\nendstream")
        inhalt = (b"q 1 1 0 rg 0 0 300 842 re f Q\n"
                  b"q 0 0 0 rg 200 0 0 140 200 582 cm /MA0 Do Q")
        objekte = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /XObject << /MA0 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
            roh_xobj(bytes([0x00] * 8)),
        ]
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%pw\n")
        offs = []
        for i, o in enumerate(objekte, start=1):
            offs.append(out.tell())
            out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
        xp = out.tell()
        out.write(f"xref\n0 {len(objekte)+1}\n".encode() + b"0000000000 65535 f \n")
        for off in offs:
            out.write(f"{off:010d} 00000 n \n".encode())
        out.write(f"trailer\n<< /Size {len(objekte)+1} /Root 1 0 R >>\nstartxref\n{xp}\n%%EOF".encode())
        return out.getvalue()

    r = requests.post(f"{BASE}/api/upload", files={"file": ("pw_streifen.pdf", _streifen_pdf(), "application/pdf")},
                      timeout=15).json()
    sid = r["id"]
    ii = requests.get(f"{BASE}/api/imageinfo/{sid}/0", timeout=10).json()
    sx = ii["bilder"][0]["xref"]
    # v0.21.15 Chirurgie: auch auf ungleichmaessigem Grund (Kante gelb/weiss)
    # verschiebbar - kein Deckel mehr, der Grund bleibt unversehrt
    r = requests.post(f"{BASE}/api/image/move/{sid}", data={
        "page": "0", "xref": str(sx),
        "alt": "[200,120,400,260]", "neu": "[300,400,500,540]"}, timeout=15).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{sid}/0", timeout=10).json()
    check("Chirurgie: ungleichmaessiger Grund kein Hindernis mehr",
          r.get("ok") and len(ii["bilder"]) == 1 and ii["bilder"][0]["bbox"] == [300.0, 400.0, 500.0, 540.0],
          str(ii["bilder"]))
    p1, o1 = _pixel(sid, 250, 190)      # alte Stelle: gelber Streifen unversehrt
    p2, o2 = _pixel(sid, 350, 190)      # alter Platz rechte Haelfte: weiss unversehrt
    check("Chirurgie: Grund an alter Stelle unversehrt (gelb/weiss-Kante)",
          o1 and p1[0] > 180 and p1[2] < 90 and o2 and min(p2) > 200, f"{p1}/{p2}")

    # ---------- v0.21.15: Chirurgie = wirkliches Verschieben (PDFgear-Paritaet) ----------
    # Platzierung wird aus dem Content-Stream herausgeschnitten und anderswo
    # neu gesetzt: kein Deckel, kein Geist, Text unter dem Bild ueberlebt -
    # auch mehrfach hin- und her- und GEDREHT (Matrix statt Rasterung).
    def _text_masken_pdf():
        def roh_xobj(daten):
            return (b"<< /Type /XObject /Subtype /Image /Width 8 /Height 8 /ImageMask true "
                    b"/BitsPerComponent 1 /Length " + str(len(daten)).encode() + b" >>\nstream\n"
                    + daten + b"\nendstream")
        inhalt = (b"BT /F1 12 Tf 72 742 Td (Beispielzeile Chirurgie) Tj ET\n"
                  b"q 0 0 0 rg 100 0 0 50 80 700 cm /MA0 Do Q")
        objekte = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources "
            b"<< /Font << /F1 7 0 R >> /XObject << /MA0 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
            roh_xobj(bytes([0x00] * 8)),
            b"<< >>",               # Platzhalter (xref 6 unbenutzt)
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%pw\n")
        offs = []
        for i, o in enumerate(objekte, start=1):
            offs.append(out.tell())
            out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
        xp = out.tell()
        out.write(f"xref\n0 {len(objekte)+1}\n".encode() + b"0000000000 65535 f \n")
        for off in offs:
            out.write(f"{off:010d} 00000 n \n".encode())
        out.write(f"trailer\n<< /Size {len(objekte)+1} /Root 1 0 R >>\nstartxref\n{xp}\n%%EOF".encode())
        return out.getvalue()

    r = requests.post(f"{BASE}/api/upload",
                      files={"file": ("pw_text_maske.pdf", _text_masken_pdf(), "application/pdf")},
                      timeout=15).json()
    check("Text-Masken-PDF hochgeladen", r.get("id"), str(r))
    tid = r["id"]
    ii = requests.get(f"{BASE}/api/imageinfo/{tid}/0", timeout=10).json()
    tx = ii["bilder"][0]["xref"]
    text_vor = requests.get(f"{BASE}/api/text/{tid}/0", timeout=10).json()["lines"]
    # AUF die Textzeile ziehen (früher: verweigert / Deckel haette Text gefressen)
    r = requests.post(f"{BASE}/api/image/move/{tid}", data={
        "page": "0", "xref": str(tx), "alt": "[80,92,180,142]", "neu": "[70,80,170,130]"},
        timeout=15).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{tid}/0", timeout=10).json()
    check("Chirurgie: Bild AUF Text verschoben",
          r.get("ok") and len(ii["bilder"]) == 1 and ii["bilder"][0]["bbox"] == [70.0, 80.0, 170.0, 130.0],
          str(ii["bilder"]))
    # Und wieder WEG - der Text muss unversehrt zum Vorschein kommen
    r = requests.post(f"{BASE}/api/image/move/{tid}", data={
        "page": "0", "xref": str(tx), "alt": "[70,80,170,130]", "neu": "[300,300,400,350]"},
        timeout=15).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{tid}/0", timeout=10).json()
    text_nach = requests.get(f"{BASE}/api/text/{tid}/0", timeout=10).json()["lines"]
    check("Chirurgie: nach Wegziehen Text unversehrt (kein Geist, kein Fleck)",
          r.get("ok") and len(ii["bilder"]) == 1 and ii["bilder"][0]["bbox"] == [300.0, 300.0, 400.0, 350.0]
          and text_nach == text_vor and _dunkel(tid, 72, 80, 220, 100) < 120,
          f"{ii['bilder']}/{_dunkel(tid, 72, 80, 220, 100)}")
    # Drehen 90°: Huelle getauscht (100x50 -> 50x100), Farben bleiben (Maskenfarbe schwarz)
    r = requests.post(f"{BASE}/api/image/rotate/{tid}", data={
        "page": "0", "xref": str(tx), "alt": "[300,300,400,350]", "winkel": "90"}, timeout=15).json()
    pr, _r = _pixel(tid, 350, 325)
    check("Chirurgie-Rotation: Huelle 50x100 um Mitte, Maske gemalt",
          r.get("ok") and r.get("rect") == [325.0, 275.0, 375.0, 375.0] and max(pr) < 120,
          f"{r}/{pr}")
    u = requests.post(f"{BASE}/api/undo/{tid}", timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{tid}/0", timeout=10).json()
    check("Chirurgie-Undo: Rotation zurueck (Matrix wortwörtlich)",
          u.get("undone") and ii["bilder"][0]["bbox"] == [300.0, 300.0, 400.0, 350.0], str(ii["bilder"]))
    # v0.21.16: GEDREHTES Objekt verschieben - der Winkel muss erhalten bleiben
    # (vorher: axis-aligned neu gesetzt -> 0 Grad + auf Huellenmass verzerrt).
    # Diskriminator: voll gemalte Maske bleibt ein GEDREHTES Viereck - die
    # Huellenecken bleiben weiss, die Mitte schwarz. Waere die Drehung weg,
    # waere die ganze Huelle schwarz.
    r = requests.post(f"{BASE}/api/image/rotate/{tid}", data={
        "page": "0", "xref": str(tx), "alt": "[300,300,400,350]", "winkel": "30"}, timeout=15).json()
    check("Chirurgie: 30 Grad gedreht (Huelle 111.6x93.3)",
          r.get("ok") and abs(r["rect"][0] - 294.2) < 1.5 and abs(r["rect"][1] - 278.4) < 1.5
          and abs(r["rect"][2] - 405.8) < 1.5 and abs(r["rect"][3] - 371.6) < 1.5, str(r))
    r = requests.post(f"{BASE}/api/image/move/{tid}", data={
        "page": "0", "xref": str(tx), "alt": "[294.2,278.4,405.8,371.6]",
        "neu": "[354.2,318.4,465.8,411.6]"}, timeout=15).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{tid}/0", timeout=10).json()
    pk, ok_k = _pixel(tid, 410, 365)      # Mitte: gedrehte Maske gemalt
    pe2, ok_e = _pixel(tid, 461, 407)     # Huellenecke: ausserhalb des gedrehten Vierecks
    check("Chirurgie: gedreht verschoben - Winkel erhalten (Mitte schwarz, Ecke weiss)",
          r.get("ok") and ii["bilder"][0]["bbox"][0] == 354.2
          and ok_k and max(pk) < 120 and ok_e and min(pe2) > 200, f"{ii['bilder']}/{pk}/{pe2}")
    # v0.21.17: GEDREHTES Objekt ERNEUT drehen - komponiert mit der Platzierung,
    # nicht aus der Huellbox neu gebaut (vorher: Verzerrung). 100x50-Maske bei
    # 30°, +15° mehr = 45° -> Huelle 106.1x106.1 (nicht huellen-gedreht 119.8!)
    r = requests.post(f"{BASE}/api/image/rotate/{tid}", data={
        "page": "0", "xref": str(tx), "alt": "[354.2,318.4,465.8,411.6]", "winkel": "15"}, timeout=15).json()
    check("Chirurgie: nochmals gedreht (30+15=45°, Huelle 106.1 quadratisch)",
          r.get("ok") and abs(r["rect"][0] - 357.0) < 1.5 and abs(r["rect"][1] - 312.0) < 1.5
          and abs(r["rect"][2] - 463.0) < 1.5 and abs(r["rect"][3] - 418.0) < 1.5, str(r))
    u = requests.post(f"{BASE}/api/undo/{tid}", timeout=10).json()
    u = requests.post(f"{BASE}/api/undo/{tid}", timeout=10).json()
    u = requests.post(f"{BASE}/api/undo/{tid}", timeout=10).json()
    u = requests.post(f"{BASE}/api/undo/{tid}", timeout=10).json()
    u = requests.post(f"{BASE}/api/undo/{tid}", timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{tid}/0", timeout=10).json()
    text_end = requests.get(f"{BASE}/api/text/{tid}/0", timeout=10).json()["lines"]
    check("Chirurgie-Undo: beide Zuege zurueck, Text immer noch heil",
          ii["bilder"][0]["bbox"] == [80.0, 92.0, 180.0, 142.0] and text_end == text_vor
          and _dunkel(tid, 72, 80, 220, 100) < 120,
          f"{ii['bilder']}/{_dunkel(tid, 72, 80, 220, 100)}")


    # ---------- v0.21.21: Drehen um die Tintenmitte verschiebt nicht (Nutzer-Fund) ----------
    # 'mitte' (die UI schickt die Tintenrahmen-Mitte) muss ein FIXPUNKT der
    # Drehung sein. Vorher wurde die neue Huelle um die Mitte ZENTRIERT - bei
    # unmittiger Tinte (Briefkopf-Masken: ING-Zug/Loewe) sprang das Objekt um
    # den Abstand Tintenmitte<->Platzierungsmitte, verkettete Drehungen
    # summierten den Versatz (90° = 50pt, +30° = 73pt im schlimmsten Fall).
    def _tinten_dreh_pdf():
        def roh_xobj(daten, w=8, h=4):
            return (b"<< /Type /XObject /Subtype /Image /Width " + str(w).encode()
                    + b" /Height " + str(h).encode()
                    + b" /ImageMask true /BitsPerComponent 1 /Length " + str(len(daten)).encode()
                    + b" >>\nstream\n" + daten + b"\nendstream")
        # nur die LINKEN 3 Spalten malen (Bits 7..5 = 0): Tinte 60x100 pt
        # innerhalb der 160x100-Vollflaeche -> Tintenmitte 50pt links der Mitte.
        # Bitmap bewusst NICHT quadratisch (8x4): die ?rot=-Huelle der zweiten
        # Drehung muss das Seitenverhaeltnis tauschen (v0.21.23-Diskriminator)
        inhalt = b"q 1 0 0 rg 160 0 0 100 200 542 cm /MA0 Do Q\n"
        objekte = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /XObject << /MA0 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(inhalt)).encode() + b" >>\nstream\n" + inhalt + b"\nendstream",
            roh_xobj(bytes([0x1F] * 4)),
        ]
        out = io.BytesIO()
        out.write(b"%PDF-1.4\n%pw\n")
        offs = []
        for i, o in enumerate(objekte, start=1):
            offs.append(out.tell())
            out.write(f"{i} 0 obj\n".encode() + o + b"\nendobj\n")
        xp = out.tell()
        out.write(f"xref\n0 {len(objekte)+1}\n".encode() + b"0000000000 65535 f \n")
        for off in offs:
            out.write(f"{off:010d} 00000 n \n".encode())
        out.write(f"trailer\n<< /Size {len(objekte)+1} /Root 1 0 R >>\nstartxref\n{xp}\n%%EOF".encode())
        return out.getvalue()

    r = requests.post(f"{BASE}/api/upload",
                      files={"file": ("pw_tinten_dreh.pdf", _tinten_dreh_pdf(), "application/pdf")},
                      timeout=15).json()
    check("Tinten-Dreh-PDF hochgeladen (Tinte unmittig)", r.get("id"), str(r))
    qid = r["id"]
    ii = requests.get(f"{BASE}/api/imageinfo/{qid}/0", timeout=10).json()
    qb = ii["bilder"][0]
    check("Tinten-Dreh-Fixtur: Flaeche 160x100, Tinte 60x100 links",
          qb["bbox"] == [200.0, 200.0, 360.0, 300.0] and qb["ink"] == [200.0, 200.0, 260.0, 300.0],
          str(qb))
    qx = qb["xref"]
    for winkel, name in (("90", "90 Grad"), ("30", "verkettet +30 Grad")):
        k = qb["ink"]
        mitte = json.dumps([(k[0] + k[2]) / 2, (k[1] + k[3]) / 2])   # Tintenmitte wie bildDrehMitte()
        r = requests.post(f"{BASE}/api/image/rotate/{qid}", data={
            "page": "0", "xref": str(qx), "alt": json.dumps(qb["bbox"]),
            "winkel": winkel, "mitte": mitte}, timeout=10).json()
        ii = requests.get(f"{BASE}/api/imageinfo/{qid}/0", timeout=10).json()
        qb = ii["bilder"][0]
        k = qb["ink"]
        abstand = max(abs((k[0] + k[2]) / 2 - json.loads(mitte)[0]),
                      abs((k[1] + k[3]) / 2 - json.loads(mitte)[1]))
        check(f"Tinten-Drehung {name}: Tintenmitte bleibt Fixpunkt",
              r.get("ok") and abstand <= 1.0, f"{r}/{qb} Abstand={abstand:.2f}pt")
    u = requests.post(f"{BASE}/api/undo/{qid}", timeout=10).json()
    u = requests.post(f"{BASE}/api/undo/{qid}", timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{qid}/0", timeout=10).json()
    check("Tinten-Drehung: doppeltes Undo zurueck auf die Ausgangslage",
          u.get("undone") and ii["bilder"][0]["bbox"] == [200.0, 200.0, 360.0, 300.0]
          and ii["bilder"][0]["ink"] == [200.0, 200.0, 260.0, 300.0], str(ii["bilder"]))

    # ---------- v0.21.22: Dreh-Vorschau schwarz (Nutzer-Fund) ----------
    # /api/image/file liefert ImageMask-xrefs als RGBA-PNG in der PLACEMENT-
    # Paintfarbe (hier: 1 0 0 rg = rot), unbemalt transparent - vorher kam das
    # rohe 1-bit-Bitmap (s/w, opaque) und die Vorschau streckte es in den
    # Tintenrahmen ("Rahmen fuellt sich schwarz beim Drehen").
    r = requests.get(f"{BASE}/api/image/file/{qid}/0/{qx}", timeout=10)
    mv = _PILImage.open(io.BytesIO(r.content)).convert("RGBA")
    px_m = mv.getpixel((1, 1))    # linke 3 Spalten = gemalt
    px_f = mv.getpixel((6, 1))    # rechte Spalten = frei
    check("Masken-Vorschau-PNG: gemalt in Paintfarbe rot, frei transparent",
          r.status_code == 200 and px_m[0] > 200 and px_m[1] < 60 and px_m[2] < 60
          and px_f[3] < 20, f"HTTP {r.status_code}/{px_m}/{px_f}")

    # ---------- v0.21.23: zweite Drehung verzerrt nicht (Nutzer-Fund Loewe) ----------
    # Bei schon gedrehten Objekten ist die imageinfo-bbox die HUELLE (groesser
    # als das Bild) - das Vorschau-Bitmap auf Huellenmass strecken verzerrt.
    # Jetzt: /api/imageinfo meldet 'winkel' (Gesamtwinkel), /api/image/file
    # nimmt ?rot= und liefert das VORGEDREHTE Bitmap auf Huellen-Seitenver-
    # haeltnis (wie die Signatur-Vorschau).
    ii = requests.get(f"{BASE}/api/imageinfo/{qid}/0", timeout=10).json()
    check("imageinfo: Gesamtwinkel 0 vor der Drehung",
          abs(ii["bilder"][0].get("winkel", 999)) < 0.5, str(ii["bilder"][0]))
    r = requests.post(f"{BASE}/api/image/rotate/{qid}", data={
        "page": "0", "xref": str(qx), "alt": json.dumps(ii["bilder"][0]["bbox"]),
        "winkel": "30"}, timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{qid}/0", timeout=10).json()
    check("imageinfo: Gesamtwinkel 30 nach der Drehung",
          r.get("ok") and abs(ii["bilder"][0].get("winkel", -1) - 30) < 0.5,
          str(ii["bilder"][0]))
    r = requests.get(f"{BASE}/api/image/file/{qid}/0/{qx}?rot=90", timeout=10)
    mv = _PILImage.open(io.BytesIO(r.content)).convert("RGBA")
    p_o, p_u = mv.getpixel((1, 1)), mv.getpixel((1, 6))
    check("Vorschau-Bitmap ?rot=90: 8x4-Canvas wird 4x8-Huelle, oben rot, unten frei",
          mv.size == (4, 8) and p_o[0] > 200 and p_o[3] > 200 and p_u[3] < 20,
          f"{mv.size}/{p_o}/{p_u}")
    u = requests.post(f"{BASE}/api/undo/{qid}", timeout=10).json()
    ii = requests.get(f"{BASE}/api/imageinfo/{qid}/0", timeout=10).json()
    check("Dreh-Undo: Winkel zurueck auf 0",
          u.get("undone") and abs(ii["bilder"][0].get("winkel", -1)) < 0.5, str(ii["bilder"][0]))


    # ---------- v0.21.11: Textfarbe (Nutzer-Fund: gruener Text wurde schwarz) ----------
    # Zwei Fallen: Das Farbfeld des PDFW-TXT-Markers wurde hinter spacing/leading
    # nicht mehr geparst (seit v0.14.4), und der AP-Builder teilte die 0-1-Farbe
    # zusaetzlich durch 255. Beides endete in stillem Schwarz.
    import pymupdf
    farbe_pfad = os.path.join(FIXDIR, "pw_test_farbe.pdf")
    fsrc = pymupdf.open()
    fsrc.new_page().insert_text((72, 90), "Farbprobe", fontsize=12)
    fsrc.save(farbe_pfad)
    fsrc.close()
    rd = requests.get(f"{BASE}/api/open", params={"q": farbe_pfad}, timeout=10).json()
    fdid = rd["id"]
    r = requests.post(f"{BASE}/api/annot/text/{fdid}", data={
        "page": "0", "rect": "[100,100,260,132]", "text": "gruen bezahlt",
        "size": "16", "font": "helv", "color": "0,0.6,0"}, timeout=10).json()
    gruen_xref = r.get("xref")
    lann = requests.get(f"{BASE}/api/annots/{fdid}/0", timeout=10).json()
    ltxt = next((a for a in lann if a.get("xref") == gruen_xref), None)
    check("Textfarbe in der Eigenschaftenliste",
          ltxt and len(ltxt.get("color") or []) == 3
          and all(abs(ltxt["color"][i] - v) < 0.01 for i, v in enumerate([0, 0.6, 0])), str(ltxt))
    requests.post(f"{BASE}/api/save/{fdid}", timeout=15)
    fdoc = pymupdf.open(farbe_pfad)
    ap_streams = []
    for fpg in fdoc:
        for fa in fpg.annots() or []:
            if fa.type[1] == "FreeText":
                _t, apw = fdoc.xref_get_key(fa.xref, "AP/N")
                ap_streams.append(fdoc.xref_stream(int(apw.split()[0])) or b"")
    fdoc.close()
    check("Textfarbe im Appearance-Stream (0 0.6 0 rg)",
          any(b"0 0.6 0 rg" in s for s in ap_streams), str(ap_streams[:1]))
    # Bestands-Heilung: Datei im Alt-Zustand (Marker gruen, AP schwarz) oeffnen -
    # der Server baut den AP beim Oeffnen aus der Markerfarbe neu.
    kaputt_pfad = os.path.join(FIXDIR, "pw_test_farbe_kaputt.pdf")
    bsrc = pymupdf.open()
    bpg = bsrc.new_page()
    ba = bpg.add_freetext_annot(pymupdf.Rect(100, 100, 260, 132), "alt gruen", fontsize=16,
                                fontname="Helv", text_color=(0, 0, 0))
    ba.update()
    bsrc.xref_set_key(ba.xref, "NM", "(PDFW-TXT:helv:16:0,0.6,0:0:0)")
    bsrc.save(kaputt_pfad)
    bsrc.close()
    rk = requests.get(f"{BASE}/api/open", params={"q": kaputt_pfad}, timeout=10).json()
    kid = rk["id"]
    lann2 = requests.get(f"{BASE}/api/annots/{kid}/0", timeout=10).json()
    ktxt = next((a for a in lann2 if a.get("type") == "text"), None)
    check("Altbestand: Farbe aus dem Marker gelistet",
          ktxt and abs((ktxt.get("color") or [0, 0, 0])[1] - 0.6) < 0.01, str(ktxt))
    requests.post(f"{BASE}/api/save/{kid}", timeout=15)
    kdoc = pymupdf.open(kaputt_pfad)
    geheilt = False
    for fpg in kdoc:
        for fa in fpg.annots() or []:
            if fa.type[1] == "FreeText":
                _t, apw = kdoc.xref_get_key(fa.xref, "AP/N")
                geheilt = geheilt or b"0 0.6 0 rg" in (kdoc.xref_stream(int(apw.split()[0])) or b"")
    kdoc.close()
    check("Altbestand geheilt: AP-Farbe aus Marker", geheilt, "")

    # ---------- v0.21.24: Druckpfad in Druckeraufloesung (Nutzer-Fund: unscharfer Ausdruck) ----------
    # Der Wrapper druckt jetzt per GDI: /api/druckinfo liefert Seitenmasse,
    # /api/druckseite rendert je Seite in Drucker-DPI (mit Annotationen) - statt
    # des alten iframe-Drucks mit 120-dpi-Bildschirm-Rastern.
    pd = requests.get(f"{BASE}/api/demo", timeout=15).json()
    pdid = pd["id"]
    pi = requests.get(f"{BASE}/api/druckinfo/{pdid}", timeout=10).json()
    check("druckinfo: Seitenzahl + Massen",
          pi.get("pages") == 3 and len(pi.get("groessen") or []) == 3
          and all(g[0] > 100 and g[1] > 100 for g in pi["groessen"]), str(pi))
    r = requests.get(f"{BASE}/api/druckseite/{pdid}?nr=0&dpi=150", timeout=30)
    drv = _PILImage.open(io.BytesIO(r.content))
    b0, h0 = pi["groessen"][0]
    check("druckseite: Pixel = Seitenmasse x dpi (150)",
          r.headers.get("content-type") == "image/png"
          and abs(drv.size[0] - b0 / 72.0 * 150) < 3 and abs(drv.size[1] - h0 / 72.0 * 150) < 3,
          f"{drv.size} vs {b0}x{h0}pt")
    # Annotationen muessen im Druckbild liegen (annots=True): Stempel setzen und
    # seine Farbe an der Stempelmitte nachweisen. Eigene Wegwerf-Signatur, denn
    # ts1 wird frueher in der Suite umbenannt.
    buf2 = io.BytesIO()
    _PILImage.new("RGBA", (300, 100), (20, 60, 160, 255)).save(buf2, "PNG")
    dsig = requests.post(f"{BASE}/api/signature/upload",
                         files={"file": ("DruckSig.png", buf2.getvalue(), "image/png")},
                         data={"remove_bg": "0"}, timeout=10).json()["file"]
    r = requests.post(f"{BASE}/api/stamp/{pdid}", data={
        "page": "0", "x": "100", "y": "100", "width": "140", "fname": dsig}, timeout=10)
    assert r.ok and r.json().get("ok"), r.text
    r = requests.get(f"{BASE}/api/druckseite/{pdid}?nr=0&dpi=150", timeout=30)
    da = _PILImage.open(io.BytesIO(r.content)).convert("RGB")
    k = (int((100 + 70) / 72.0 * 150), int((100 + 23) / 72.0 * 150))
    pr = da.getpixel(k)
    check("druckseite enthaelt Annotationen (Stempel blau an der Mitte)",
          pr[0] < 100 and pr[2] > 120, f"{pr} @ {k}")
    # v0.21.26: annots=0 druckt pures Papier (Druckdialog-Option "ohne
    # Markierungen") - der Stempel muss WEG sein
    r = requests.get(f"{BASE}/api/druckseite/{pdid}?nr=0&dpi=150&annots=0", timeout=30)
    oh = _PILImage.open(io.BytesIO(r.content)).convert("RGB")
    pr2 = oh.getpixel(k)
    check("druckseite annots=0: Stempel weg (weiss)",
          r.headers.get("content-type") == "image/png" and pr2[0] > 230 and pr2[1] > 230,
          f"{pr2} @ {k}")

    # --- Sperrzustand nach Server-Neustart (zweiter Prozess, anderer Port) ---
    PORT2 = PORT + 1
    srv2 = subprocess.Popen([EXE, "--port", str(PORT2)], creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(40):
            time.sleep(0.5)
            try:
                if requests.get(f"http://127.0.0.1:{PORT2}/api/health", timeout=2).json().get("ok"):
                    break
            except Exception:
                pass
        B2 = f"http://127.0.0.1:{PORT2}"
        from urllib.parse import quote
        r = requests.get(B2 + f"/api/signature/file/{quote(pwfile)}", timeout=5)
        check("Nach Neustart: Abruf gesperrt (401)", r.status_code == 401, str(r.status_code))
        r = requests.post(B2 + "/api/signature/unlock", data={"fname": pwfile, "password": "falsch"}, timeout=20)
        check("Falsches Passwort abgewiesen", r.status_code == 401, str(r.status_code))
        r = requests.post(B2 + "/api/signature/unlock", data={"fname": pwfile, "password": "geheim"}, timeout=20)
        check("Richtiges Passwort entsperrt", r.ok and r.json().get("ok"), str(r.status_code))
        r = requests.get(B2 + f"/api/signature/file/{quote(pwfile)}", timeout=5)
        check("Entsperrt liefert PNG", r.status_code == 200 and r.content[:4] == b"\x89PNG", str(r.status_code))
    finally:
        srv2.kill()
except Exception as e:
    failures.append("Ausnahme: " + repr(e)[:200])
finally:
    srv.kill()
    # Aufgeraeumt: Wegwerf-Signaturen loeschen, damit nichts uebrig bleibt
    sigdir = os.path.join(os.path.dirname(EXE), "signatures")
    try:
        for fn in os.listdir(sigdir):
            if fn.startswith(("TestSig", "UndoSig", "TestSig Umbenannt", "PwSig", "DruckSig")):
                os.remove(os.path.join(sigdir, fn))
    except Exception:
        pass
    for tmpf in (os.path.join(TMPD, "pw_test_saveas.pdf"), os.path.join(TMPD, "pw_test_saveas_burn.pdf"),
                 os.path.join(TMPD, "pw_test_bild.pdf")):
        try:
            os.remove(tmpf)
        except Exception:
            pass
    try:
        shutil.rmtree(FIXDIR, ignore_errors=True)
    except Exception:
        pass
    print("Testserver gestoppt")
    print("ERGEBNIS: " + ("ALLE PASS" if not failures else "FEHLER: " + ", ".join(failures)))
