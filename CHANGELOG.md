# FederPDF — Changelog

Alle Versionen vom ersten Prototyp bis heute. Datum: 2026-10-22.

## v0.21.28 — Druckdialog: Seitenbereich-Steuerung und Mausrad geradegerückt
- Fehlerbehobung (Nutzer-Fund: Pfeil-Klicks im Seitenbereich schienen beim
  falschen Feld zu landen): Jeder Pfeilklick lud sofort ein neues Vor-
  schaubild per HTTP-Abruf auf dem Benutzeroberflächen-Thread — bei Klick-
  serien staute sich die Warteschlange, der Dialog reihte sich verzögert
  durch und die gerade nicht gemeinten Zahlen schienen sich zu ändern, während
  der Cursor im vorherigen Feld stehen blieb. Jetzt: **Zahlen reagieren
  sofort**, das Vorschaubild kommt 250 ms nach dem letzten Klick (Debounce).
- **Fokus folgt dem Feld**: Spinner-Klicks fokussieren jetzt ihr eigenes
  Zahlenfeld (WinForms tut das nicht von selbst — der Cursor blieb im
  vorherigen stehen und Pfeiltasten änderten weiter dessen Wert); beim
  Aktivieren von „Seitenbereich" landet der Cursor im Von-Feld.
- **Mausrad blättert wieder** (Nutzer-Fund: „wird gezoomt, das ist falsch"):
  Mausrad wechselt die Seite (bzw. scrollt den gezoomten Inhalt), Zoom nur
  noch mit Strg+Mausrad oder über die Zoomknöpfe — Hinweis steht unter der
  Vorschau.

## v0.21.27 — Vorschau zoombaren, Skalierung sichtbar, Absturz-Fix
- Fehlerbehobung (Nutzer-Fund: „kurz die Druckvorschau gesehen, dann hat sich
  die App beendet"): Die Vorschauseite kam als GDI+-Bild direkt aus dem
  HTTP-Stream — GDI+ liest solche Bilder träge, der Stream-Puffer konnte aber
  per Garbage Collector eingeholt werden, und der nächste Malvorgang lief in
  eine Access Violation. Jetzt liefert der Abruf eine eigenständige Bitmap-
  Kopie ohne Stream-Abhängigkeit.
- **Vorschau zoombaren** (Nutzer-Wunsch): Mausrad über der Vorschau zoomt
  (30–400 %), dazu −/+/„Angepasst"-Knöpfe; Doppelklick setzt die Anpassung
  zurück. Große Zoomstufen laufen im scrollbaren Bereich.
- **Skalierung sofort sichtbar** (Nutzer-Wunsch): Die Vorschau zeigt die
  Seite jetzt **auf dem Blatt komponiert** — exakt wie der Druck sie platziert
  (Anpassen: in die druckbare Fläche, querlaufende Seiten automatisch gedreht;
  fester Maßstab: 1:1 zentriert, Überhänge gekappt wie am Papier). Jeder
  Wechsel der Skalierung (auch benutzerdefiniert %) ist unmittelbar in der
  Vorschau zu sehen.

## v0.21.26 — Druckdialog: Duplex, Skalierung, Theme, „ohne Markierungen"
- Erweiterung nach PDFgear-Vorbild (Nutzer-Wünsche):
  - **Duplex**: Einseitig / Beidseitig – Kante lang / Beidseitig – Kante kurz,
    wird an den Druckertreiber durchgereicht.
  - **Skalierung**: „An Seitenrand anpassen" (bisheriges Verhalten mit
    automatischer Drehung) / „Tatsächliche Größe" (100 %, keine Drehung —
    Überhänge clippt der Treiber wie bei Acrobat) / „Benutzerdefiniert"
    (25–400 %).
  - **„Signaturen, Markierungen und Formulare drucken"** abwählbar — der
    Ausdruck ist dann pures Papier (neuer `annots`-Parameter von
    `/api/druckseite`); die Vorschau schaltet live mit, sie zeigt stets
    den echten Druckinhalt.
  - **Theme folgt der App**: Der Dialog übernimmt das helle oder dunkle
    Design der Web-UI (Farben aus deren Palette); Umschalten im Hauptfenster
    wirkt ab dem nächsten Druckdialog-Öffnen.

## v0.21.25 — Druckdialog im PDFgear-Stil
- Überarbeitung (Nutzer-Wunsch nach PDFgear-Vorbild): Der Druckdialog ist
  jetzt **deutlich größer** (1080×700 statt 760×560) und im Stil der App —
  große **Seitenvorschau links** auf dunklem Papier-Hintergrund (blätterbar
  per Pfeiltasten oder Mausrad), rechts die **Einstellungsspalte** mit
  Drucker, Kopien und Seitenbereich, wobei die Optionen die Seitenzahlen
  anzeigen („Alle Seiten (3)", „Aktuelle Seite (2)"). Eigene Titelzeile mit
  Schließen-Knopf und DWM-Eckenrundung wie das Hauptfenster; der
  Drucken-Knopf ist als Akzentknopf hervorgehoben.
- **DPI-Scaling repariert:** Der Dialog blieb auf Monitoren mit Skalierung
  (Notebook 150 %) auf 96-dpi-Entwurfsmaß „zu klein" — jetzt skaliert er wie
  das Hauptfenster mit (`AutoScaleMode.Dpi`), und die Vorschau rendert in
  Monitordpi (bis 192 dpi statt 96) — auch das Vorschaubild ist scharf.

## v0.21.24 — Drucken scharf, mit eigener Vorschau
- Fehlerbehobung (Nutzer-Fund: „Ausdruck komplett unscharf"): Der alte
  Druckweg schickte eine HTML-Seite mit **120-dpi-Bildschirm-Rastern** durch
  den WebView2-Druckdialog — raus kam ein verwaschenes Bildschirmfoto statt
  eines Dokuments. Neuer Weg: Der Wrapper druckt selbst per GDI. Der Server
  liefert je Seite (`/api/druckseite`) ein PNG in **Druckerauflösung** (bis
  600 dpi, mit Signaturen, Texten, Formen und Formularwerten — auch
  ungespeicherte Änderungen), `/api/druckinfo` die Seitenmaße; der Wrapper
  zeichnet jede Seite maßhaltig und seitenverhältnisgetreu auf das Papier
  (automatisch gedreht bei Hoch/Quer-Kollision, zentriert, innerhalb der
  druckbaren Fläche). Beweise: Stiller Headless-Druck über „Microsoft Print
  to PDF" ergibt effektiv **600×600 dpi** pro A4-Seite (vorher 120), Suite
  prüft Auflösung und Annotationen im Druckbild (133 Checks).
- **Eigener Druckdialog mit Vorschau** (Nutzer-Rückmeldung: „keine
  Druckvorschau zu sehen"): Der Windows-Standarddruckdialog zeigt keine
  Vorschau und frißt beim Öffnen Sekunden bis Minuten, weil er den Status
  schlafender Netzwerkdrucker abfragt. FederPDF zeigt jetzt einen eigenen
  Dialog im App-Design: links die **Seitenvorschau aus dem echten
  Druckinhalt** (blätterbar), rechts Drucker (nur Namensliste — keine
  Statusabfragen), Seitenbereich (alle/aktuelle/von–bis) und Kopien. Alle
  druckernahen Abfragen (Auflösung, Auftrag) laufen erst **nach** dem
  Klick im Hintergrund-Thread — die Oberfläche blockiert nie.
- Drucken geht jetzt auch über **Strg+P**; der Titel des Druckknopfes nennt
  es. Im nackten Browser (Entwicklung) bleibt der alte iframe-Weg als
  Fallback. Vom Nutzer am eigenen HP-Drucker verifiziert: 2 Seiten,
  „sieht gut aus".

## v0.21.23 — Zweite Drehung verzerrt die Vorschau nicht mehr
- Fehlerbehobung (Nutzer-Fund, ING-Löwe): Die erste Drehung sah korrekt aus,
  jede weitere verzerrte die Darstellung zunehmend. Ursache: Bei einem schon
  gedrehten Objekt ist der Platzierungsrahmen die **Hüllbox** (größer als das
  Bild selbst) — die Vorschau streckte das Bitmap auf Hüllenmaß und zerrte
  damit die Kontur auseinander. Jetzt liefert `/api/imageinfo` den
  **Gesamtwinkel** des Objekts mit, und `/api/image/file?rot=` (wie bei der
  Signatur-Vorschau) das **vorgedrehte** Bitmap auf Hüllen-Seitenverhältnis —
  die Vorschau malt es verzugfrei auf Rahmenmaß und dreht nur das Delta
  obendrauf. Betrifft nur die Live-Vorschau; das gespeicherte Ergebnis blieb
  unberührt verlustfrei.

## v0.21.22 — Dreh-Vorschau nicht mehr schwarz
- Fehlerbehobung (Nutzer-Fund): Während des Drehvorgangs füllte sich der
  Rahmen des Objekts schwarz. Zwei Ursachen: (1) Die Live-Vorschau streckte
  das komplette Bitmap (inklusive transparenter Ränder) in den engeren
  **Tintenrahmen** — die sichtbare Tinte blähte sich auf Rahmengröße auf.
  Jetzt wird das Bitmap in **Platzierungsmaßstab, um den Tinten-Offset
  versetzt**, als Hintergrund gemalt — die Tinte steht während des Zugs an
  Ort und Stelle in ihrer wahren Größe. (2) Masken-Bitmaps (Briefkopf-Logos)
  haben keine eigene Farbe, sondern werden in der Füllfarbe der Platzierung
  gemalt — das rohe 1-Bit-Bitmap erschien schwarz-weiß. `/api/image/file`
  liefert ImageMask-Objekte jetzt als PNG in genau dieser **Paint-Farbe**
  (unbemalte Pixel transparent).
- Betrifft nur die Vorschau beim Ziehen des Drehgriffs; das gespeicherte
  Ergebnis war und bleibt unverändert verlustfrei (cm-Matrix).

## v0.21.21 — Drehen verschiebt das Objekt nicht mehr zusätzlich
- Fehlerbehobung (Nutzer-Fund): Im Bearbeitungsmodus sprang ein Bild beim
  **Drehen** zusätzlich an eine andere Stelle. Ursache: Der Server verankerte
  die neue Hülle **zentriert um die Drehmitte** (die Mitte des sichtbaren
  Tintenrahmens, um die auch die Vorschau dreht) — das ist nur bei mittig
  liegender Tinte dasselbe wie eine echte Drehung um diesen Punkt. Bei
  Briefkopf-Masken (Tinte belegt nur einen Rand der Fläche) wanderte das
  Objekt um den Abstand Tintenmitte↔Platzierungsmitte, und verkettete
  Drehungen summierten den Versatz auf. Jetzt ist die Drehmitte ein echter
  **Fixpunkt** (Translation C − R·C nach der Rotationskomposition); ohne
  Mitwirkung des Parameters dreht das Bild wie bisher um seine Hüllenmitte.
- Der seltenere Ersatzpfad (Bitmap-Rasterung bei unsauberen Inhaltsblöcken)
  dreht seine Ziel-Hülle jetzt um denselben Fixpunkt. Rückgängig macht wie
  zuvor die Vorher-Matrix wortwörtlich wieder auf.

## v0.21.20 — Tintenrahmen bleibt auch beim Drehen erhalten
- Fehlerbehobung (Nutzer-Fund): Nach dem Drehen eines Bildes sprang der
  Auswahlrahmen zurück auf die **volle Bildfläche** — die Tintenmessung
  lief bisher nur bei ungedrehten Platzierungen. Jetzt werden die
  Tinten-Pixelecken durch die Platzierungs-Transformationsmatrix auf die
  Seite gerechnet: Der Rahmen bleibt in **jeder Lage** eng an der Kontur
  (bei Drehwinkeln ist er die Umbox der gedrehten Kontur — minimal größer
  als die Kontur selbst, aber deutlich enger als die Vollfläche).

## v0.21.19 — Auswahlrahmen um die sichtbare Kontur (Tintenrahmen)
- Verbesserung (Nutzer-Wunsch): Der Rahmen eines Bildes liegt jetzt eng um
  die **sichtbare Kontur**, nicht mehr um die ganze Bildfläche. Bei
  Briefkopf-Logos aus Masken-Ebenen ist die Fläche oft viel größer als die
  Tinte (beim ING-Briefkopf bedecken „ING"-Zug und Löwe je nur 15–20 % ihrer
  Ebene) — jetzt zeigt der Rahmen genau den Löwen bzw. die Buchstaben, und
  auch Klick und Griffe liegen auf der Kontur statt auf unsichtbarer Fläche.
- Innerlich rechnet FederPDF weiterhin mit der vollen Platzierung (Ziehen,
  Skalieren, Drehen, Rückgängig unverändert exakt); nur Anzeige und Klick-
  ziel sind enger. Drehen dreht um die Mitte des sichtbaren Rahmens, damit
  Vorschau und Ergebnis zusammenpassen. Voll deckende Bilder (Fotos ohne
  Transparenz) bekommen wie bisher den vollen Rahmen.

## v0.21.18 — Übereinanderliegende Bildebenen getrennt greifbar (wie PDFgear)
- Verbesserung (Nutzer-Wunsch): Besteht ein Logo aus **übereinander
  gelegten Bildebenen** (wie der ING-Briefkopf aus „ING"-Schriftzug und
  Löwe), sind diese jetzt **getrennt verschiebbar** — jede Ebene ist ihr
  eigenes Objekt. Bisher wurden exakt übereinanderliegende Ebenen als ein
  Objekt gemeinsam gezogen (das war Schadensvermeidung aus der Zeit vor
  der Echten-Verschieben-Umstellung; seitdem berührt das Ziehen einer
  Ebene die Nachbarebene nicht mehr).
- Bedienung wie in Word/PowerPoint: **Klick** wählt die oberste Ebene,
  **Alt+Klick** schaltet durch den Stapel durch. Ziehen, Skalieren,
  Drehen und Rückgängig gelten für die gewählte Ebene allein; die
  Auswahl bleibt nach jedem Zug auf der Ebene liegen.

## v0.21.17 — Erneutes Drehen gedrehter Bilder verzerrt nicht mehr
- Fehlerbehobung (Nutzer-Fund): Drehte man ein **bereits gedrehtes** Bild
  nochmals, wurde es **verzerrt** — dieselbe Wurzel wie beim Verschieben:
  Die umschließende Box eines gedrehten Bildes wurde als Bildgröße
  fehlinterpretiert. Das Drehen komponiert jetzt mit der bestehenden
  Platzierung (Bildmaße und Winkel stecken in der Transformationsmatrix);
  jede weitere Drehung addiert sich sauber auf den Ist-Winkel, das
  Seitenverhältnis bleibt immer erhalten.

## v0.21.16 — Gedrehte Bilder behalten beim Verschieben ihren Winkel
- Fehlerbehobung (Nutzer-Fund): Verschob man ein **gedrehtes** Bild, fiel
  es auf 0 Grad zurück und wirkte **verzerrt** — das Verschieben setzte
  die Bildmaße neu an, statt die Drehung mitzunehmen (die umschließende
  Box eines gedrehten Bildes ist größer als das Bild selbst und wurde
  fälschlich als neue Bildgröße interpretiert). FederPDF erhält jetzt die
  komplette Transformation (Drehung + Seitenverhältnis) beim Ziehen und
  Skalieren; nur die Position (bzw. Größe) ändert sich. Rückgängig
  funktioniert wie gehabt.

## v0.21.15 — Wirklich verschieben wie im Profi-Editor (PDFgear-Parität)
- Große Verbesserung (Nutzer-Beweis an PDFgear): Eingebettete Bilder
  werden beim Verschieben/Drehen jetzt **wirklich verschoben** — die
  alte Platzierung wird aus dem Seiteninhalt herausgeschnitten und an der
  neuen Stelle neu gesetzt. Bisher wurde die alte Stelle nur überdeckt.
- Was das bringt: Bilder lassen sich nun **auch auf Text oder Fotos
  verschieben und wieder wegziehen** — der darunterliegende Inhalt bleibt
  unversehrt (keine weißen Flecken mehr, keine „Hintergrund nicht
  einfarbig"-Verweigerung bei sauberen Platzierungen). Kein „Geist" mehr,
  der versehentlich wieder auftaucht.
- Drehen ist jetzt verlustfrei: Statt das Bild neu zu berechnen wird eine
  Drehmatrix gesetzt — auch mehrfaches Drehen erhält die Originalqualität.
- Rückgängig funktioniert weiterhin beliebig oft und stellt die
  Ausgangslage exakt wieder her (die ursprüngliche Platzierung wird
  gespeichert und wiederhergestellt).
- Sicherheit: Die Segment-Chirurgie greift nur bei sauber isolierbaren
  Platzierungen (der Block darf außer dem Bild nichts anderes malen).
  Andernfalls fällt FederPDF auf das frühere Überdecken-Verfahren zurück.

## v0.21.14 — Bilder bleiben anpackbar und behalten ihre Griffe
- Fehlerbehobung (Nutzer-Fund): Hatte man ein Bild **auf einen Textbereich**
  verschoben, ließ es sich danach nicht mehr anfassen — die unsichtbaren
  Textzeilen-Flächen (für Markieren/Kopieren) lagen über dem Bild und haben
  den Mauszeiger abgefangen. Bilder liegen jetzt über der Textebene (wie
  Annotationen schon immer): das Bild ist wieder greifbar, egal worüber es
  liegt. In Lesemodus und Werkzeugmoden ändert sich nichts — dort sind die
  Bilder weiterhin ruhig gestellt, und Text markieren funktioniert überall.
- Fehlerbehobung (Nutzer-Fund): Nach jedem Verschieben/Skalieren/Drehen
  verlor das Bild seine **Griffe** (Größenanker, Drehgriff) und musste erst
  wieder angeklickt werden. Die Auswahl wird jetzt über den Seiten-Neuaufbau
  gerettet: Nach dem Zug ist das Objekt sofort wieder ausgewählt, mit Griffen
  und Eigenschaftenleiste an der neuen Position.
- Bleibt gewollt: Liegt ein Bild einmal auf Text/Foto, verweigert FederPDF
  das weitere Verschieben mit einer klaren Meldung — das Überdecken der
  alten Stelle würde dort sichtbaren Inhalt auslöschen (Strg+Z macht den
  Zug rückgängig).

## v0.21.13 — Logo-Farben bleiben erhalten, Deckel folgen dem Hintergrund
- Fehlerbehobung (Nutzer-Fund): Nach dem Verschieben des Briefkopf-Logos
  war der Löwe **orange-los** — das Logo erschien nur noch schwarz-weiß.
  Grund: Solche Logos sind 1-Bit-Maskenbilder ohne eigene Farbe; ihre
  Farbe steht im Seiteninhalt als „Füllfarbe beim Malen" (ING navy,
  Löwe orange). Beim Wiedereinsetzen an der neuen Stelle fehlte dieser
  Farbbefehl, und die Maske wurde in Schwarz gemalt. FederPDF liest jetzt
  die Paint-Farbe je Platzierung aus dem Seiteninhalt und schreibt sie
  beim Verschieben **mit** (auch beim Rückgängig-Machen).
- Auch auf **farbigem Hintergrund** ist Verschieben jetzt sauber: FederPDF
  misst die Hintergrundfarbe rund um das Objekt und überdeckt die alte
  Stelle in genau dieser Farbe statt in Weiß. Ist der Hintergrund nicht
  einfarbig (Foto, Verlauf, Kanten), wird der Zug mit einer klaren
  Meldung verweigert — jede Überdeckung hätte dort einen sichtbaren
  Fleck hinterlassen. Das Rückgängig-Machen funktioniert in beiden
  Fällen farbrichtig.

## v0.21.12 — Bildverschieben kopiert nicht mehr (Briefkopf-Logos)
- Fehlerbehobung (Nutzer-Fund, ING-Wertpapierbrief): Verschob man das
  Logo oben links, blieb ein **weißes, weiter verschiebbares Objekt**
  zurück — jeder Zug darauf erzeugte eine **weitere sichtbare Kopie**
  des Logos, und der Löwe daneben war verschwunden.
- Grund: Solche Briefköpfe bestehen aus **gestapelten 1-Bit-Maskenbildern**
  (eine Ebene „ING", eine Ebene Löwe, exakt übereinander). FederPDF
  überdeckt beim Verschieben die alte Stelle weiß und merkt sich die
  überdeckte Alt-Platzierung als unsichtbar — der Merker erkannte aber
  nur „normale" Bilder. Maskenbilder wurden übersehen, die Sicherheits-
  abschaltung griff, und der Geist blieb dauerhaft anklickbar.
- Behoben: Maskenbilder zählen jetzt mit; überdeckte Alt-Stellen sind
  nicht mehr greifbar (nichts liegt mehr als weißes Objekt herum).
- Außerdem: Erkannte übereinanderliegende Bildebenen (Briefkopflogo!)
  ziehen jetzt **als ein einziges Objekt** — der Löwe wandert mit und
  bleibt erhalten. Drehen am merger Objekt dreht alle Ebenen gemeinsam,
  Strg+Z macht den Zug in einem Rutsch rückgängig.

## v0.21.11 — Textfarbe wird endlich übernommen
- Fehlerbehobung (Nutzer-Fund): Legte man neuen Text in einer Farbe an
  (z. B. grün), blieb bzw. wurde er **stets schwarz** — egal, welche
  Farbe man im Farbfeld wählte. Zwei Fehler wirkten zusammen, beide seit
  der Einführung des Zeichenabstands (v0.14.4): Die Textfarbe steckt
  unsichtbar in einer Merkzeile am Textobjekt, hinter Schrift, Größe,
  Zeichen- und Zeilenabstand — beim Wiederauslesen lief das Auswerten am
  Zeilenabstand sticken und fiel still auf Schwarz zurück; zusätzlich
  rechnete der Darstellungsbauer den kleinen Farbwert (0–1) fälschlich
  als großen (0–255) und erzeugte damit ebenfalls fast Schwarz.
- Beides behoben. **Bestehende Dateien heilen automatisch:** Beim Öffnen
  vergleicht FederPDF jetzt die gemerkte Farbe mit der tatsächlich im
  Dokument gespeicherten — weichen sie ab (Altbestand mit schwarz
  geratenem Text), wird der Text aus der gemerkten Farbe neu aufgebaut.
  Betroffene Dokumente einfach öffnen und speichern, fertig.
- Das Einbrennen („Speichern mit eingebrannten Änderungen") farbiger
  Texte nutzt dieselbe korrigierte Farbzuweisung.

## v0.21.10 — Textauswahl frisst nicht mehr die ganze Seite
- Fehlerbehobung (Nutzer-Fund): Zog man eine Textmarkierung über das Ende
  des Textes hinaus, färbte sich die **ganze Seite blau** — der Mauszeiger
  hatte unsichtbar das Seitenbild „mitmarkiert", und Chromium überzieht ein
  ausgewähltes Bild mit einem blauen FlächenTon. Das Seitenbild, die
  Textebene und alle Oberflächen-Teile (Miniaturen, Seitenleisten,
  Kopf-/Fußzeile) nehmen jetzt grundsätzlich nicht an der Textauswahl teil —
  wählbar sind nur die Textzeilen und Eingabefelder. Zieht man über das
  Textende hinaus, bleibt die Markierung einfach stehen, wie bei anderen
  PDF-Programmen.

## v0.21.9 — Abgerundete Ecken, deutlich sichtbar
- Das Programmfenster bekommt gerundete Ecken. Der Standardbogen von
  Windows 11 war dabei kaum zu erkennen (Nutzer-Runde 2), darum schneidet
  das Fenster sich selbst mit einem deutlich größeren Radius (14 px bei
  100 % Skalierung, mitwachsend) — der bunte Rand und der Fensterschatten
  laufen mit um die Kurve.
- Maximiert bleibt das Fenster eckig, wie man es von anderen Programmen
  kennt. Auf Windows 10 (keine Rundung im Standard) bleibt alles beim
  Alten — die Anfragen werden dort einfach ignoriert.
- Nachgereicht (Nutzer-Hinweis mit Screenshot): Der Schließen-Knopf saß
  mit einem toten dunklen Streifen vor dem Fensterrand. Die breite
  Greifzone fürs Größeneinstellen (8/12 px) liegt jetzt unsichtbar über
  dem Rand — sichtbar bleibt nur noch das dünne Farbband (4 px), an dem
  der Knopf bündig anliegt. Die Zone lässt sich genauso greifen wie
  bisher.

## v0.21.8 — Text markieren wie im Browser, Zoom-Knöpfe als Icons
- **Dynamischer Zeiger:** Über Text (auch unsichtbarem OCR-Text) wird der
  Mauszeiger zur Textmarkierung — ziehen markiert zeichengenau, Strg+C
  kopiert, Doppelklick wählt ein Wort, Rechtsklick bietet das übliche
  Menü mit Kopieren. Über leeren Stellen greift die Hand und verschiebt
  die Seite wie gewohnt. Gilt in beiden Zuständen, also auch im
  Lesemodus.
- **Zoom-Knöpfe (PDFgear-Art):** Der Textknopf „Passend" ist drei kleinen
  Icon-Knöpfen gewichen — ganze Seite, Seitenbreite und 1:1 (Original-
  größe), jeweils mit Tooltip. Der aktive Zoom-Modus färbt sich akzent,
  bis man frei hinein- oder herauszoomt.
- **Immer noch da:** Doppelklick auf eine Zeile bearbeitet den Originaltext,
  Umschalt+Klick sammelt Zeilen, Alt+Ziehen wählt ganze Zeilen auf einmal
  (KI-Auswahl), und der Lösch-Modus markiert Zeilen wie bisher. Das
  Kopieren einer ganzen Zeile per einfachem Klick entfällt — den Text
  markiert man jetzt direkt.
- Kleinigkeit am Rande: Esc beim Bearbeiten des Originaltexts konnte in
  einem seltenen Fall intern doppelt anlaufen (gleiche Falle wie 0.16.3,
  diesmal auf dem Abbruchpfad) — beseitigt.

## v0.21.7 — Signatur-Kacheln: Vorschau nach dem Entsperren, Drag & Drop-Hinweis
- Nach dem Eingeben des Passworts zeigt die Kachel wieder das kleine
  Vorschaubild der Signatur statt des Schlosses — ein kleiner grüner
  Schloss-Hinweis an der Ecke zeigt an, daß sie bis zum Programmende
  entschlüsselt ist. Gesperrte Kacheln zeigen weiterhin das Schloss.
- Jede Kachel trägt jetzt einen Tooltip mit der Platzier-Anweisung
  („per Drag & Drop aufs Papier ziehen – Klick wählt nur aus"); derselbe
  Hinweis steht im Fußtext des Signatur-Menüs.

## v0.21.6 — GitHub-Link im Über-Dialog
- Der Über-Dialog (Klick auf Logo/FederPDF) nennt jetzt auch Quellcode und
  Downloads mit Link zum GitHub-Repository — der Link öffnet den
  Standard-Browser, nicht das App-Fenster. Zweisprachig wie der Rest der
  Oberfläche.

## v0.21.5 — Fenstergriff final und eine einzige Oberkante
- **Griff unten rechts (Vorbild Affinity):** eine winzige 12×12-Punktematrix
  in der Fußleistenecke — dezente Punkte, kaum sichtbar, mit dem passenden
  Größen-Pfeil als Cursor. Ein Druck darauf löst den nativen
  Größenänderungs-Zug des Fensters aus; die Maus bleibt dabei gefaßt. Der
  weiße Kasten aus 0.21.4 ist vollständig entfernt.
- **Oberkante gehört nur noch der Kopfzeile:** Der Trikolore-Streifen läuft
  in beiden Designs genau einmal über die Fensterbreite (vorher malte der
  Fensterrahmen ein zweites Band darunter — das wirkte als dicker
  Doppelstreifen mit Naht-Artefakten). Die breiten unsichtbaren Ziehzonen
  bleiben an den Seiten und unten erhalten, die Oberkante selbst zieht das
  Fenster (Kopfzeile wie gewohnt).

## v0.21.4 — Fensterrand besser greifbar
- Ziehzone an allen Kanten auf 8 px (bei 100 % Skalierung) bzw. 12 px (bei
  150 %) verbreitert — sie war mit 4 px halb so breit wie bei normalen
  Windows-Programmen und daher schwer zu treffen. Der sichtbare
  Trikolore-Streifen bleibt 4 px dünn; der zusätzliche Rand ist in der Farbe
  der angrenzenden Oberfläche gehalten und fällt nicht auf.

## v0.21.3 — Keine Scrollbalken-Reste mehr bei spät geladenen Riesenseiten
- **Nutzer-Fall:** Das automatisch eingepaßte Dokument zeigte Seite 1 korrekt,
  aber horizontale (und übertriebene vertikale) Scrollbalken blieben — die
  Seiten 3 und 4 standen weiterhin in dreifacher Breite im Strom.
- **Ursache 1:** Diese Seiten luden erst NACH dem automatischen Einpassen; auf
  die aktuelle Zoomstufe wurde niemand mehr gezogen. `buildPage` wendet die
  Zoomstufe jetzt selbst auf jede frisch geladene Seite an (idempotent).
- **Ursache 2:** Die Breiten-Rückrechnung des Seitenmaßstabs nahm dabei fälschlich
  die aktuelle Zoom-DPI als Render-DPI — hatte der Auto-Einpassen die Zoomstufe
  aber bereits geändert, während das Bild noch lud, kam ein vielfach zu großer
  Wert heraus. Die Rückrechnung nutzt jetzt die DPI, mit der das Bild
  tatsächlich gerendert wurde (`dataset.renderedDpi`).

## v0.21.2 — Riesenseiten werden beim Öffnen automatisch eingepaßt
- Der v0.21.1-Fix machte „Passend" bei übergroßen Scan-Seiten wieder
  wirksam — aber beim Öffnen stand so ein Dokument weiterhin bei 100 %
  als mehrfach fensterbreites Monster da. Jetzt paßt FederPDF die Seiten
  beim Öffnen automatisch ein, sobald die erste Seite mehr als doppelt so
  breit ist wie der Sichtraum; normale Dokumente (A4 & Co.) bleiben
  unverändert bei 100 %.
- „Passend" vor dem Seitenladen führt nicht mehr zu Unsinnswerten (früher
  rechnete eine 0-Breite kurz auf 400 % hoch), sondern wartet schlicht.

## v0.21.1 — „Passend" funktioniert jetzt auch bei Riesenseiten
- **Nutzer-Fall:** Ein 4-seitiger Scan (Seitenbox 2400×3390 pt statt A4) zeigte
  sich im Fenster als riesige Ecke bei „100 %", und „Passend" reagierte nicht —
  auf dem externen Monitor. Auf dem Notebook-Display wirkte alles korrekt.
- **Zwei Ursachen:** (1) Der Seitenmaßstab (`pageW`) wurde erst mit der
  asynchronen Text-Antwort gesetzt — bei großen Scan-Seiten queueen sich diese
  Antworten hinter den Seitenrenderings ein, und solange der Wert fehlte, waren
  Zoom und „Passend" wirkungslos. Er steht jetzt schon beim Bildladen zur
  Verfügung (aus der natürlichen Bildbreite zurückgerechnet; der Serverwert
  präzisiert später). (2) Die Zoom-Untergrenze war starr 0,3 — bei 2400-pt-
  Seiten entspricht das 960 px Mindestbreite: In ein schmales Fenster paßte
  die Seite nie, der erste „Passend"-Klick klemmte an der Grenze, jeder
  weitere war ein No-op. Die Untergrenze ist jetzt seitenabhängig (A4 bleibt
  exakt bei 0,3; Riesenseiten dürfen bis auf ~240 px Mindestbreite
  herauszoomen).

## v0.21.0 — Sprachumschalter: Oberfläche auf Deutsch oder Englisch
- **DE/EN-Umschalter in der Kopfzeile** (neben dem Design-Knopf): Die gesamte
  Oberfläche — Werkzeugleisten, Kontextmenüs, Dialoge, Kurzhlfe, Statuszeile,
  Tooltipps — steht auf Deutsch und Englisch zur Verfügung. Die Wahl wird wie
  alle Einstellungen serverseitig gespeichert und beim nächsten Start
  wiederhergestellt.
- **Technik:** Deutsch bleibt die Quellsprache (steht unverändert im Markup).
  Ein Wörterkatalog tauscht statische Texte/Kurzinfos/Platzhalter beim
  Umschalten (Originaltexte werden gemerkt), dynamisch erzeugte Texte holen
  ihre Sprache über einen zweisprachigen Helfer direkt an der Entstehungsstelle.
  Fehlt eine Übersetzung, erscheint der deutsche Text — nichts bricht.
- **Auch der Fenster-Wrapper folgt:** Startbildschirm, Fehlerseite und der
  „ungespeicherte Änderungen“-Dialog beim Schließen sprechen mit (Startwert
  aus den Einstellungen, laufend per Nachricht von der UI nachgezogen).
- Die KI-Antwortsprache folgt der Umschaltung (Systemprompt), die
  Übersetzungs-Zielsprachen heißen auch auf Englisch richtig — der Inhalt von
  Dokumenten (Demo, Texte) bleibt natürlich unverändert.

## v0.20.4 — Ein Name überall: EXE und Namespace heißen FederPDF
- **Letzte Alt-Namen beseitigt:** Die Programm-EXE (`PdfWerkstatt.exe`), der
  Hintergrundserver (`PdfWerkstattServer.exe`) und der .NET-Namespace trugen
  noch den alten technischen Namen. Alles heißt jetzt durchgängig FederPDF:
  `FederPDF.exe`, `FederPDFServer.exe`, Namespace `FederPDF`, Projektdatei
  `FederPDF.csproj`, Programm-Icon `federpdf_icon.ico`. Kein
  Funktionsunterschied — nur der Name.
- **Für Umsteigende:** Die Dateizuordnung („.pdf immer mit diesem Programm
  öffnen") und eine evtl. Taskleisten-Verknüpfung müssen einmalig neu auf
  `FederPDF.exe` gesetzt werden. Beim Selbstbauen ändern sich die Befehle:
  `build_server.ps1` baut nach `app\dist\FederPDFServer\`, der Wrapper per
  `dotnet publish wrapper\FederPDF.csproj`. Der Dateiname der Testsuite
  bleibt unverändert `tests/pdfwerkstatt_test.py`.

## v0.20.3 — Fenster skaliert korrekt beim Wechsel zwischen Monitoren
- **Nutzer-Fall:** Bei zwei Bildschirmen mit unterschiedlicher Skalierung
  (z. B. Notebook 150 %, externer Monitor 100 %) behielt das Fenster beim
  Hinüberschieben seine Pixelgröße — es war auf dem Zielfenster größer als
  der Bildschirmbereich, und nach dem Zurückschieben blieben Schrift und
  Menüs zu klein (die Oberfläche hing im Rastermaßstab des anderen Monitors).
- **Ursache:** Das Programmfenster antwortete auf die Windows-Nachricht
  `WM_GETDPISCALEDSIZE` („Wie groß willst du auf dem anderen Bildschirm
  sein?") mit der unveränderten Fläche — der Größenänderungsvorschlag in
  `WM_DPICHANGED` lief dadurch leer.
- **Fix:** Das Fenster berechnet die Zielgröße jetzt selbst (linear zur
  DPI-Änderung) und übernimmt sie beim Monitorwechsel; maximierte Fenster
  überläßt weiterhin das System. Der Wechsel zwischen Monitoren skaliert das
  Fenster nun in beide Richtungen verlustfrei.

## v0.20.2 — Bild-Geister beseitigt, Kopfzeile bleibt einreihig
- **Nutzer-Fall:** Beim Verschieben einer eingebetteten Signatur (Bild) wurde
  jedes Mal eine unsichtbare Kopie angelegt — sie ließ sich auf leerem Papier
  „anfassen“ (Auswahlrahmen ohne Inhalt) und ihr Verschieben erzeugte eine
  sichtbare Dublette. Außerdem sprang bei jeder Auswahl die Seite, weil das
  Menü oben wegen der Bild-Koordinatenfelder in zwei Reihen umbrichte.
- **Unsichtbare Kopien (Geister) werden nicht mehr gemeldet:** `/api/image/move`
  überdeckt die alte Stelle weiß und setzt das Bild neu ein — die alte
  Platzierung bleibt dabei (bewusst) in der Datei und wurde von `/api/imageinfo`
  weiter als verschiebbares Objekt gemeldet. Der Server erkennt diese Geister
  jetzt markerlos über die Content-Stream-Reihenfolge (`get_bboxlog` listet
  Bilder und Pfade vereint; ein Bild, das von einem SPÄTER gezeichneten,
  deckungsweißen Rechteck voll überdeckt wird, ist unsichtbar und fällt aus
  der Objektliste). Das wirkt ohne Merker auch bei bereits gespeicherten
  Dateien und nach Undo; unberührte Bilder bleiben selbstverständlich
  gemeldet. Aufräumen per Redaction/delete_image war bewusst KEIN Weg — dort
  wären überlappende Nachbarbilder mit verschwunden.
- **Weißdeckel-Kante:** Der Whiteout stand exakt auf dem Bild-Rect, die
  gerasterte Bildkante schimmerte danach hauchfein als farbiger Rest an der
  alten Stelle. Der Deckel übersteht jetzt 1 pt (Verschieben, Drehen, Undo).
- **Eigenschaftenleiste schwebt:** Die Leiste (X/Y/Breite/Höhe/Winkel) ist aus
  dem Fluss der Kopfzeile genommen und schwebt als Panel unter der Kopfzeile
  rechts (direktes Kind von `header`, nicht von `.kopfzeile` — deren
  horizontales Scrollen würde das Panel abschneiden). Das Menü bleibt
  einreihig, die Seite springt beim Auswählen nicht mehr.
- Tests am Quellstand: API-Suite 27 Checks PASS (dreimaliges Verschieben
  inkl. überlappendem Zug, Kantenproben weiß, Undo, Speichern + Neuöffnen
  filtert weiter, unberührte Bilder bleiben). Browser-E2E: Kopfzeile bleibt
  einreihig (49 px) und die Seite springt nicht — mit und ohne Auswahl;
  Auswahl, Ziehen und Feld-Setzen funktionieren, keine Geister-Overlays.

## v0.20.1 — Fix: Zeilen-Sammlung kaperte den Doppelklick des Originaltext-Editors
- **Nutzer-Fall:** Nach dem Sammeln einer Zeile (Umschalt+Klick, hellblaue
  Markierung) öffnete ein Doppelklick auf eine ANDERE Zeile immer den Editor
  der gesammelten Zeile — kein anderer Text war noch editierbar, und die
  Sammlung ließ sich nicht sichtbar loswerden (nur Umschalt+Klick auf genau
  diese Zeile).
- **Fix (Doppelklick entscheidet, was geöffnet wird):** Doppelklick auf eine
  gesammelte Zeile bearbeitet weiterhin alle gesammelten (das Sammel-Feature
  bleibt). Doppelklick auf irgendeine andere Zeile verwirft die Sammlung und
  öffnet die angeklickte Zeile (bzw. ihren Block) — mit Statusmeldung.
- **Aufräumschranken:** Esc leert die Sammlung (neue Stufe in der Esc-Kette,
  bevor der Modus zurückgesetzt wird), und jeder Abschluss des
  Originaltext-Editors (Commit, Abbruch, Entfernen) räumt die Sammlung mit weg.
- E2E am Quellstand: 5 Szenarien (Bug-Reproduktion, Fix, Esc, Sammel-Feature,
  Commit-Flow) bestanden; Suite gegen den neuen Build ALLE PASS.

## v0.20.0 — Umbenennung: FederPDF (vorher Blattwerk)
- Die App heißt jetzt **FederPDF** — die Feder steht fürs Schreiben und
  Unterschreiben, das „PDF"-Präfix für das, was es ist. Grund: Der bisherige
  Name Blattwerk (seit v0.14.0) kollidiert mit einem bereits existierenden
  PDF-Tool gleichen Namens (GitHub, seit August 2026) sowie weiteren
  gleichnamigen Angeboten — vor der Veröffentlichung als Open Source
  umgestellt, damit das Projekt von Anfang an eindeutig auffindbar ist.
- Umgestellt: Fenstertitel/Taskbar, Splash-Screen, Kopfzeilen-Brand,
  HTML-Titel, Über-Dialog, Demo-Dokument („FederPDF Demo-Dokument"),
  Fehler-/Hinweisdialoge, FastAPI-Titel, csproj <Product>, README,
  KI-Systemprompt. **Bewusst unverändert** (wie schon bei v0.14.0): Exe-Namen
  PdfWerkstatt.exe/PdfWerkstattServer.exe, Namespace, Buildskripte —
  Deploy-Pfade und Dateizuordnung laufen unverändert weiter. Auch der
  Projektordner heißt jetzt `federpdf` (statt pdf-werkstatt; venv und
  Build-Ausgaben wurden dabei regeneriert). Das GitHub-Repo heißt `federpdf`
  (bleibt bis auf Weiteres privat; Veröffentlichung folgt mit dem neuen Icon).
- App-Logik/Verhalten unverändert. Suite 89 PASS gegen das neue Deployment
  (Vollswap wegen geändertem Wrapper).

## v0.19.3 — Open-Source-Vorbereitung (AGPL-3.0)
- Blattwerk wird als freie Software veröffentlicht — Lizenz: **GNU AGPL-3.0**
  (Pflicht wegen PyMuPDF; siehe LICENSE und „Drittanbieter“ im README).
- README (deutsch mit englischer Kurzfassung) und LICENSE ergänzt; die
  Testsuite liegt im Repo (`tests/pdfwerkstatt_test.py`, erzeugt ihre
  Fixtures jetzt selbst).
- `server.py`: Entwicklungs-BASE ist skriptrelativ statt absolut;
  `PdfWerkstattServer.spec`: Icon-Pfad über SPECPATH statt absolut. Das
  App-Verhalten ist unverändert, Suite 89 PASS gegen das Deployment.

## v0.19.2 — Umschalter Lesen/Bearbeiten: Auge ↔ Stift-auf-Dokument
- **Icon-Verwechslung behoben (Nutzer-Hinweis):** Der Bearbeiten-Knopf trug
  einen Stift — zu ähnlich zum Stift-Symbol des Werkzeugs „Markieren“. Der
  Umschalter zeigt jetzt ICON + BESCHRIFTUNG je Zustand (Anzeige = Zustand):
  **Auge + „Lesen“** im Lesemodus, **Dokument mit Stift (MDL2 QuickNote,
  E70B) + „Bearbeiten“** im Bearbeitungsmodus (der Auge↔Stift-Gegensatz aus
  der Icon-Recherche des Nutzers; der Titel-Tooltip wechselt mit).
- Kurzhilfe-Zeile angepasst („Knopf ‚Lesen/Bearbeiten‘ (Auge ↔ Stift)“).
  Server/Verhalten unverändert, Suite 89 PASS gegen das Deployment.

## v0.19.1 — Bilder skalieren und drehen
- **Eingebettete Bilder sind jetzt vollwertige Objekte** (bisher nur verschiebbar):
  Ecke unten rechts ziehen skaliert proportional (Anker oben links, wie bei
  Signaturen), der runde ↻-Griff über dem Bild dreht frei (Umschalt rastet auf
  15°), Rechtsklick bietet „Drehen (90°)“ und „Drehen (−90°)“, und die
  Eigenschaftenleiste zeigt X/Y/Breite/Höhe zum exakten Setzen. Bilder bleiben
  angeklickt ausgewählt (gestrichelter Rahmen + Griffe), Klick aufs Papier hebt
  ab. Scans/Ganzseitenbilder bleiben fix (wie bisher).
- **Technik:** Skalieren geht über den bestehenden `/api/image/move`-Weg
  (weiß überdecken + `insert_image` in das Ziel-Rect — das streckt bereits,
  Skalieren war serverseitig also gratis). Drehen ist neu (`/api/image/rotate`):
  Bildbytes werden vom jetzigen Zustand um den DELTA-Winkel vorgedreht
  (eingebettete Bilder tragen keine Rotations-Metadaten wie der Signatur-NM-
  Marker), alte Stelle weiß überdeckt, gedrehte Hülle um die alte Kastenmitte
  gesetzt. Beides mit Undo (Strg+Z). Bildbytes mit Transparenz (SMask) werden
  korrekt kombiniert (`_bild_bytes_vom_xref`); derselbe Endpunkt `/api/image/file`
  liefert die Live-Vorschau beim Drehen (Bild im Kasten, CSS dreht mit).
  Das Winkel-Feld bleibt Signaturen vorbehalten — bei Bildern ist der
  aufkumulierte Winkel nach dem Neuladen unbekannt.
- **Suite um 9 Checks erweitert** (Bildinfo, PNG mit Alpha, Skalierung,
  90°-Hülle inkl. Rückgabe-Rect, Undo ×2, 30°-Drehung mit Datei-Level-Beweis:
  gespeicherte Datei frisch mit PyMuPDF geöffnet, Hülle 243×221 um 180/190
  verifiziert). Suite 89 PASS, deployed. E2E im Browser: Auswahl/Griffe,
  Resize (+30 pt proportional), Kontextmenü-90°, Drehgriff mit Live-Vorschau,
  Abwahl per Papier-Klick — am Quell-Server und am Deployment bewiesen.
  Unterwegs gefunden und behoben: Bild-Overlays trugen kein `data-page`
  (Kontextmenü-Drehung schickte page=NaN → FastAPI 422).

## v0.19.0 — Lesemodus: die App startet ruhig
- **Neuer Startzustand:** Beim Öffnen eines PDFs ruht das Papier — kein
  Block-Highlight beim Überfahren, kein Doppelklick-Originaltext-Editor,
  Bilder/Formularfelder nicht greifbar (Nutzer-Wunsch: das sofortige
  Hover-Markieren „kann irritierend wirken“). Suche, Zoom, Seitenwahl
  funktionieren wie gehabt. Ein Klick auf den neuen Kopfzeilen-Knopf
  **„Bearbeiten“** (Stift, links neben „Auswahl“) schaltet das heutige
  Verhalten frei; derselbe Knopf oder der neue Kontextmenü-Eintrag kehrt in
  den Lesemodus zurück.
- **Keine Sackgasse:** Wer im Lesemodus ein Werkzeug wählt (Text, Markieren,
  Zeichnen, Löschen), eine Signatur aufs Papier zieht oder OCR startet,
  schaltet die Bearbeitung automatisch frei (Auto-Promotion) — sichtbar am
  aufleuchtenden Knopf. Der Knopf nutzt den Such-Lupen-Zustand `.an` (nicht
  `.active`), die gleitende Modus-Pill bleibt unberührt.
- **Aufräumen mit Esc-Semantik:** Abschalten verwirft offene Text-Editoren
  (kein heimlicher Commit), wählt Objekte ab und bringt die Modus-Pill auf
  „Auswahl“ zurück. Bewährt im E2E gefunden: setMode allein ließ den
  Originaltext-Editor offen — jetzt schließen `cancelOriginalEdit` +
  `cancelInline` vorab. Startzustand bewusst nicht persistiert (deterministisch).
- Kurzhilfe um „Lesemodus“ ergänzt; Doppelklick-/Bild-Handler tragen Guards
  (dispatched Events ignorieren pointer-events). E2E: Startzustand, Hover an/
  aus, Editor + Esc, Promotion, Kontextmenü bewiesen. .zcode/ in .gitignore.

## v0.18.13 — Suche wie bei PDFgear: Knopf + schwebendes Feld statt Dauer-Leiste
- **Suchleiste raus aus der Kopfzeile (Nutzer-Wunsch nach PDFgear-Screenshot):**
  Statt der breiten Such-Leiste (Eingabe 150 px + Zähler + zwei Pfeile, dauerhaft
  sichtbar) gibt es nur noch einen kleinen Lupen-Knopf in der Leiste. Er öffnet
  ein kompaktes schwebendes Suchfeld unter der Kopfzeile rechts: Lupe, Eingabe,
  Trefferzähler (x/y), Hoch/Runter-Pfeile und Schließen-X — eins zu eins das
  PDFgear-Muster. Die Kopazeile gewinnt ~230 px Platz für die Werkzeuge.
- **Strg+F** öffnet die Suche (wie PDFgear/Word) und fokussiert die Eingabe;
  **Eingabe** springt zum nächsten Treffer, **Umschalt+Eingabe** zum vorherigen,
  **Esc** (im Feld) schließt. Schließen räumt auf: Eingabe leer, Treffer-
  Markierungen weg, Zähler leer, Knopf-Zustand aus. Suchlogik (runSearch/
  hitNav, debounce 350 ms, Sprung zum Treffer) unverändert.
- Kurzhilfe um eine Zeile „Suchen" ergänzt (Funktion ist jetzt hinter dem
  Knopf verborgen). Such-Knopf nutzt eigenen Zustand `.an` (nicht `.active`,
  damit die gleitende Modus-Pill ihn nicht ansteuert).
- E2E im Browser: Knopf öffnet/fokussiert, „Seite" findet 21 Treffer mit
  Markierungen, Eingabe blättert 1→2→3, Esc schließt+räumt, Strg+F bewiesen;
  Deployment per Feature-Token verifiziert. Suite 80 PASS.

## v0.18.12 — Fenster an der Marke ziehen: nun wirklich (Native-Drag-Falle)
- **Folgefix zu v0.18.11 (Nutzer-Meldung: „Fenster lässt sich an der Marke
  immer noch nicht ziehen“):** Die Schwellen-Logik war in Ordnung, aber das
  Logo ist ein <img> — der Browser startet beim Ziehen darauf ein natives
  HTML5-Drag&Drop, das die Pointer-Ereigniskette abbricht, bevor die
  6-px-Schwelle den Rahmen-Move auslösen kann (gleiche Klasse wie die
  Signatur-Kacheln v0.17.10). Fix: dragstart an der Marke preventDefault
  + Logo-Img draggable=„false“. Nutzer bestätigt: Ziehen funktioniert.
- **Test-Lektionen (in AGENTS.md/Gedächtnis festgehalten):** Synthetische
  PointerEvents umgehen das native DnD — sie bewiesen die Logik, nicht das
  Verhalten; echte OS-Eingaben brauchen SetProcessDpiAwareness(2). Fenster-
  Testpositionen NUR nach Abfrage der Monitor-Topologie wählen (Monitore
  überlappen: Zweitmonitor beginnt bei x=−264 — Testfenster davor stand
  offscreen, Nutzer-Kritik). Deployment-Kontrolle: robocopy-Erfolg per
  Datei-Existenz prüfen, nie per echo-Kette (ein fehlgeschlagener Swap
  ließ server\ leer und die App mit „Server nicht gefunden“-Dialog starten).
- Suite 80 PASS.

## v0.18.11 — Schlankerer Fensterrand, Fenster wieder an der Marke ziehbar
- **Fensterrand 6 → 4 px (Nutzer-Wunsch „etwas dünner“):** Der Rahmen
  (Größe-Zonen + Trikolore-Band) geht auf 4 px zurück; WM_NCHITTEST und
  OnPaint lesen das Padding dynamisch, die Zieh-Greifzonen schrumpfen mit
  und bleiben greifbar. Gemessen in der echten App: Farbband gleichmäßig
  7 px (vorher 10) auf ganzer Breite inkl. Fensterknopf-Zone.
- **Marke zieht wieder (Nutzer-Wunsch):** Logo/„Blattwerk“ behält den
  Info-Klick UND verschiebt das Fenster beim Ziehen — wie eine native
  Titelleistenecke: Erst ab 6 px Bewegung wird der Rahmen-Move gestartet
  (dessen modaler Loop schluckt das Loslassen, v0.17.7/8), ohne Bewegung
  zählt das Loslassen als Klick und öffnet den Über-Dialog. Die Ausnahme
  der Marke in der Kopfzeilen-Ziehfläche bleibt (sie regelt Klick/Zug
  selbst); Doppelklick auf die Marke maximiert weiterhin nicht.
- Beweis im Browser (synthetische PointerEvents, chrome-Mock): Klick →
  Dialog ohne Nachricht; 30-px-Zug → genau ein „fenster|drag“, kein
  Dialog; 3-px-Kurzzug → Dialog; Doppelklick → keine Nachricht.
- Suite 80 PASS. Wrapper (Padding) + UI; beide neu gebaut und deployed.

## v0.18.10 — Logo mit Original-Transparenz (wirkt freundlicher)
- **Die Eckenmaske fliegt raus (Nutzer-Wunsch):** Das Logo/Ikon wurde bisher
  auf ein abgerundetes Quadrat (22 %) maskiert — gegen den dunklen Chrome
  wirkte es kantig. Jetzt wird die ORIGINALE Transparenz der Nutzer-Bild-
  quelle respektiert: Papierstapel + Band schweben frei (Quelle:
  wrapper/icon_quelle.png, liegt jetzt im Repo).
- **Neu gebaut:** app/static/logo.png (512 px, Original-Alpha),
  wrapper/pdfwerkstatt_icon.ico (Multi-Size 16–256 px, aus der 1024er-
  Quelle) — EXE-Icon im Taskbar/Explorer per Wrapper-Publish erneuert und
  per Icon-Extraktion aus der deployeden EXE nachgewiesen.
- **Rahmen-Effekte entfernt, die ein Quadrat zeichneten:** Header-Marke
  ohne 1-px-Ring (box-shadow), Splash-/Fehlerbildschirm ohne weichen
  Kastenschatten hinter dem Logo.
- Alte Versionen als logo_alt.png / pdfwerkstatt_icon_alt.ico gesichert
  (unversioniert, .gitignore). Suite 80 PASS.

## v0.18.9 — Trikolore-Kante läuft wieder durch die Fensterknopf-Zone
- **Harte Kante oben rechts beseitigt (Nutzer-Meldung: „unschöne Kante, die
  vier Symbole wirken höher"):** Die eigene 3-px-Trikolore-Kante der Kopfzeile
  (header::before) wurde von der opaken .fensterzone (z-Index 3) auf ihren
  ~180 px überdeckt — der Verlauf riss dort ab, die Ecke oben rechts wirkte
  kahl und die Knöpfe dadurch „verschoben". Die Kante liegt jetzt mit
  z-Index 4 ÜBER der Zone und läuft durchgehend bis zum rechten Rand
  (im App-Screenshot gemessen: Goldband wieder 10 px auf ganzer Breite,
  vorher Stufe 9→6 px an der Zonengrenze). Die Knopfreihen standen exakt —
  Zentren 24 px — der Eindruck kam vom Kantenabriss. 3-px-Streifen
  überlappt nichts Sichtbares (Knöpfe beginnen erst darunter).
- Suite 80 PASS. Nur-UI-Änderung (1 Zeile + Kommentar).

## v0.18.8 — KI-Assistent: Breite verstellbar, bündig unter der Kopfzeile, klares Schließen
- **Breite veränderbar (Nutzer-Wunsch):** Linke Panelkante ist ein Breitengriff
  (7 px, Akzent bei Hover); Zug klemmt bei 300 px bzw. Fensterbreite minus 80.
  Die Breite bleibt in einstellungen.json (prefs.kiBreite) und steht beim
  nächsten Start wieder so.
- **Panel beginnt unter der Kopfzeile (Nutzer-Meldung: „etwas tiefer, bündig“):**
  Vorher überdeckte das Panel die Kopfzeilen-Zone incl. Fensterknöpfen. Jetzt
  setzt es beim Öffnen auf header.offsetHeight — bündig mit der Oberkante des
  Papierbereichs, auch wenn die Leiste bei schmalen Fenstern umbricht.
  Design-Knopf, Minimieren/Maximieren/Schließen bleiben sichtbar und klickbar.
- **Schließen-Knopf eindeutig (Nutzer-Meldung):** Das nackte X des Panels saß
  an derselben Ecke wie das Fenster-Schließen-X und wirkte verwechselnd.
  Jetzt ein beschrifteter Knopf „Schließen“ (eingerahmt, Panel-Stil) mit
  Hinweis im Tooltip („schließt NICHT das Programm“).
- Suite 80 PASS (nur UI-Änderungen, Server unverändert).

## v0.18.7 — Pfeilspitzen in richtiger Größe, Pfeil per Umdrehen skalieren
- **Pfeilspitzen endlich so groß wie im PDF (Nutzer-Meldung: „Spitzen kürzer
  als der Pfeil"):** Das Overlay zeichnete die Spitze 4× Strichbreite (min.
  7 px) — MuPDFs /LE im gespeicherten PDF aber 8,8× (Halbbreite 4,5×, im
  AP-Stream ausgemessen). Ein gemeinsamer Eckpunkt-Rechner (`kopfEcken`)
  nutzt jetzt auf beiden Seiten die MuPDF-Proportionen: Live-Vorschau beim
  Zeichnen, Overlay und PDF zeigen identische Spitzen. Offene Spitze (O)
  mit denselben Eckpunkten wie ClosedArrow, wie bei MuPDF.
- **Gefüllte Spitze auch in der DATEI:** MuPDF füllt ClosedArrow nur bei
  gesetztem /IC — vorher war die Spitze im gespeicherten PDF hohl (`h S`),
  während das Overlay sie füllte. `/api/annot/shape` und `/api/annot/style`
  setzen jetzt über `_line_stil_anwenden` /IC = Strichfarbe (und entfernen
  es, wenn keine C-Spitze mehr da ist).
- **Pfeil durch Ziehen UMdrehen (Nutzer-Wunsch):** Der Größe-Anker unten
  rechts darf jetzt über die Gegenseite hinausgezogen werden (Formen ohne
  Mindestmaß/Clamp) — der Pfeil kehrt dabei seine Richtung (nach unten ↔
  nach oben, links ↔ rechts), die Spitze folgt dem Griff. Punkte wandern
  als Absolute mit (vorzeichenrichtige Abbildung alt→neu, Flip inklusive),
  das Rechteck wird danach wieder normalisiert (Server-Antwort-Rect).
  Rechteck/Oval/Tinte dürfen ebenfalls spiegeln; Markierungen/Text/
  Signaturen behalten ihr Mindestmaß.
- **Latenter v0.18.5-Bug mitbehoben:** shapemove schrieb die Punkte im
  PDFW-SHAPE-NM-Marker nie zurück — nach Seitenwechsel/Neuladen zeichnete
  das Overlay die ALTE Stelle (Rect war neu, Punkte alt). `_shape_
  transformieren` schreibt jetzt /L bzw. InkList UND die NM-Punkte
  (strukturerhaltend bei Tinte). Der Undo-Guard (`alt_r.x1 > alt_r.x0`)
  akzeptiert gespiegelte Rechtecke, damit auch der Flip sauber rückgängig
  geht (sonst sx=sy=1 und /L blieb geflippt).
- Suite 80 PASS (neu: Pfeil-Move-NM-Sync, Flip + Flip-Undo, /LE+/IC im
  Datei-Byte).

## v0.18.6 — Über-Dialog am Logo
- **Klick auf Logo/„Blattwerk" in der Kopfzeile öffnet den Über-Dialog:** zentriertes
  kleines Modal (bekanntes miniBox-Muster) mit Logo in groß, Name, Versionsanzeige,
  PDF-Engine-Stand (PyMuPDF), Kurzbeschreibung (lokal, ohne Cloud, telemetriefrei)
  und Entwickler-Zeile („Idee und Entwicklung: Guido · © 2026"). Schließen per Knopf,
  Esc oder Klick neben den Dialog; erneuter Klick auf die Marke schaltet um.
- **Tooltip an der Marke:** „Über Blattwerk – Programm- und Versionsinfo" (natives
  title-Attribut, wie bei allen Knöpfen der Leiste).
- **Robustheit:** Die Marke ist aus der Fenster-Ziehfläche der Kopfzeile ausgenommen —
  der modale Titelleisten-Move des Wrappers (HTCAPTION) würde das Loslassen schlucken
  (v0.17.7/8-Falle); der Klick läuft über klickRobust (pointerdown+pointerup mit
  Nahbereich). Doppelklick auf die Marke maximiert das Fenster nicht mehr.
- **Server:** neue APP_VERSION-Konstante und Endpunkt /api/version (Name, Version,
  PyMuPDF-Stand) sowie Route /logo.png (Logo in Originalgröße für den Dialog).
  Version künftig bei jedem Release in server.py mitziehen.
- Suite 76 PASS (neu: Versions-Endpunkt, Logo-Route).

## v0.18.5 — Pfeil-Fix: Verschieben/Skalieren + Spitzen, Linienstil, Dicke
- **Pfeil, Linie und Tinte lassen sich wieder verschieben/skalieren (Nutzer-
  Meldung: Rahmen erscheint, der Pfeil passiert nichts):** Beim Verschieben
  wurde nur der Kasten gesetzt, die im Overlay geführten Punkte blieben — die
  Strichform zeichnete sich relativ zum neuen Kasten wieder an der ALTEN
  Stelle (der Rahmen „entfernte" sich sichtbar vom Objekt). Punkte und Quads
  werden jetzt beim Ziehen live mittransformiert und beim Loslassen
  dauerhaft nachgezogen (betrifft auch Markierungen und Tinte).
- **Pfeilspitzen und Linienstil einstellbar:** Neue Auswahlfelder in der
  Zeichen-Leiste (sichtbar bei Linie/Pfeil): Spitze gefüllt/offen/keine/
  beidseitig gefüllt/offen sowie Durchgezogen/Gestrichelt/Gepunktet. Wirken
  beim Zeichnen und auf das ausgewählte Objekt (neben Strichdicke und
  Farbe, die schon gingen). Der Stil zieht mit ins PDFW-SHAPE-NM-Marker
  (8. Feld, z. B. „OO1"), Undo stellt ihn komplett wieder her, alte Marker
  bleiben lesbar (arrow → C0, line → N0).
- Server: /api/annot/shape und /api/annot/style nehmen spitze/linienstil;
  /LE + /Border-Dash direkt gesetzt (MuPDF rendert beides korrekt, Probe
  mit Pixel-Differenz bestätigt).

## v0.18.4 — Markier-Leiste: Symbole statt Dropdown + Mausrad für Deckkraft
- **Art der Markierung als Symbolknöpfe:** Das Dropdown (Marker/Unterstrichen/
  Durchgestrichen/Wellenlinie) ist durch vier kleine Symbole ersetzt — Stift
  für Marker, „A" mit Linie darunter/darhindurch/als Wellenlinie —
  stilgleich mit den Zeichen-Werkzeugen (Nutzer-Wunsch).
- **Deckkraft per Mausrad:** Beide %-Felder (Marker-Deckkraft, Form-Deckkraft)
  ändern sich jetzt mit dem Mausrad in 5er-Schritten, wie Größe und
  Zeichenabstand schon vorher.
- Nebenbei gefunden und gefixt: Die change-Listener-Kette der Werkzeugleiste
  griff noch auf das entfernte mkArt-Select zu — null.addEventListener brach
  die Script-Ausführung an dieser Stelle ab (alles danach Ungebundene, u. a.
  sämtliche Markier-/Zeichen-Bindings, lief nicht mehr). Kette ist jetzt
  null-sicher (?.).

## v0.18.3 — Zeichnen: ein konsistenter Werkzeug-Zustand + Kontextmenü
- **Objekte im Zeichen-Werkzeug direkt greifbar (wie PDFgear):** Angelegte
  Formen, Markierungen, Texte und Signaturen lassen sich im Zeichen-Modus
  anklicken und verschieben, ohne zum Auswahl-Werkzeug zu wechseln — die
  freie Papierfläche zeichnet weiterhin. Der gemeldete Mischzustand (Anzeige
  „Zeichnen", Cursor Hand, Klick schiebt das Dokument) ist damit aufgelöst.
- **Auswahl schaltet den Werkzeug-Zustand passend:** Wird im Auswahl-Modus
  eine Form/Markierung angeklickt, wechselt die App wirklich in den Zeichen-
  Modus — mit dem zum Objekt passenden Unterwerkzeug (Pfeil anklicken →
  Pfeil-Werkzeug aktiv). Anzeige, Cursor und Verhalten sind immer eins.
  Text/Signatur wechseln bewusst nicht (Text-Modus würde beim nächsten Klick
  aufs Papier einen Editor öffnen statt zu verschieben).
- **Strg/Umschalt auch beim Nachträglich-Vergrößern:** Am Anker unten rechts
  erzwingt die Taste wie beim Zeichnen Quadrat beziehungsweise Kreis
  (Nutzer-Wunsch).
- **Rechtsklick-Kontextmenü ausgebaut (Nutzer-Vorschlag):** Rechtsklick aufs
  Papier bietet „Letzte Form bearbeiten" (wählt die zuletzt gezeichnete
  Form/Markierung aus — Stil, Größe, Position in der Leiste oben) und den
  Werkzeugwechsel mit Häkchen am aktiven Werkzeug. Rechtsklick auf ein
  Objekt: Stil/Löschen (wie bisher) plus Werkzeugwechsel. Der Radiergummi
  bleibt davon unberührt (Klick löscht statt auszuwählen).

## v0.18.2 — Zeichnen: Strich-Greifen, Quadrat/Kreis-Zwang, Werkzeug-Anzeige
- **Linie, Pfeil und Tinte direkt am Strich greifbar:** Dünne Striche waren
  praktisch nicht zu treffen. Jede Strichform bekommt eine unsichtbare
  breite Klickbahn (16 px) unter dem Strich — anklicken und ziehen
  funktioniert jetzt auch mitten auf der Linie (Nutzer-Meldung: Pfeil ließ
  sich nicht verschieben). Im Zeichen-/Markier-Modus ist die Bahn bewusst
  abgeschaltet, damit sie das Zeichnen nicht abfängt; Formen zeigen den
  Verschiebe-Cursor.
- **Quadrat/Kreis-Zwang:** Rechteck/Oval mit gedrückter Strg-Taste (oder
  Umschalt, wie in anderen Programmen üblich) zeichnen exakt Quadrat/Kreis —
  schon live in der Vorschau (Nutzer-Wunsch).
- **Werkzeug-Anzeige folgt der Auswahl:** Ist ein Objekt ausgewählt, leuchtet
  der passende Werkzeug-Knopf (Text → T, Markierung → Markieren, Form →
  Zeichnen) samt gleitender Markierung statt des Auswahl-Werkzeugs — vorher
  blieb „Auswahl" aktiviert, obwohl die Formen-Leiste offen war.

## v0.18.1 — Fix: Werkzeug-Symbole Rechteck/Oval
- Die beiden Zeichen-Werkzeuge zeigten zufällig gewählte MDL2-Symbole (Crop-
  beziehungsweise formasatz-artig statt der Form) — Nutzer-Meldung mit Screenshot.
- Beide sind jetzt eigene Inline-SVGs wie Linie/Pfeil/Tinte: abgerundetes
  Rechteck bzw. Oval, einheitliche Strichstärke.

## v0.18.0 — Großausbau: Markieren, Zeichnen, OCR, KI-Assistent, Dokument-Schriften
Fünf neue Funktionsbereiche (Wunschliste vom 2026-10-09), Suite jetzt 74 Checks (alle PASS):

- **Markieren:** Werkzeug „Markieren" — Text mit gedrückter Maustaste aufziehen
  (waagerecht entlang einer Zeile genügt!) und per Marker, Unterstrich,
  Durchstreichen oder Wellenlinie hervorheben. Farbe, Deckkraft (Marker) und
  Strichstärke (Linien) in der Kontextleiste oben. Markierungen sind echte
  Markup-Annotationen mit eigenem Appearance-Stream (MuPDF kennt keine
  Strichstärke bei Unter-/Durchstreichen) — verschieb- und skalierbar über
  QuadPoints-Neuberechnung, löschbar, Strg+Z-fähig. Ohne Textebene (Scan)
  wird die Auswahlfläche selbst markiert.
- **Zeichnen:** Rechteck (mit/ohne Füllung), Oval, Linie, Pfeil und Tinte
  (Freihand) — Strichdicke, Strich- und Füllfarbe, Deckkraft einstellbar.
  Formen sind Square/Circle/Line/Ink-Annotationen (Stil im PDFW-SHAPE-NM-
  Marker), verschieben/skalieren rechnet Punkte (L/InkList/QuadPoints) mit,
  Pfeilspitzen per /LE. Radiergummi löscht angeklickte Objekte.
- **Werkzeugleiste dynamisch:** Statt Dauerschriftleiste zeigt der Kopf
  je Werkzeug/Auswahl genau EINE Kontextleiste (Text | Markieren | Zeichnen);
  Auswahl schlägt Modus. Plus neue Knöpfe OCR und KI.
- **OCR:** Knopf „OCR" — Texterkennung für Seiten ohne Textebene (Scans),
  Sprachen Deutsch + Englisch (tessdata im Paket, Tesseract steckt im
  PyMuPDF-Wheel). Pro Seite Fortschritt, danach durchsuchbar/kopierbar/
  markierbar; nicht rückgängig machbar (reine Zusatzebene).
- **KI-Assistent (BYOK):** Panel mit Chat (Antworten live gestreamt),
  „Zusammenfassen" (ganzes Dokument), „Auswahl übersetzen" (Alt+Ziehen).
  Konfiguration nach Adobe-Vorbild: Anbieter (OpenAI, z.ai, OpenRouter,
  Anthropic, Google, Ollama lokal, OpenAI-kompatibel eigen), URL, API-
  Schlüssel, Modellliste vom Anbieter ladbar; Aufgaben zuordenbar. Schlüssel
  liegen nur lokal in einstellungen.json; alle Anbieter-Anfragen laufen über
  den lokalen Server.
- **Dokument-Schriften:** Im Text-Werkzeug stehen die im PDF eingebetteten
  Schriften zur Auswahl (Overlay lädt sie als @font-face; der Server bettet
  sie in den Freitext-AP per Glyph-ID-Stream ein, Helvetica-Fallback bei
  fehlenden Subset-Glyphen).
- **Server aufgeräumt:** toter Doppelblock (save bis _txt_spacing, byte-
  identisch) entfernt — 2033 statt 1415 Zeilen ohne Verhaltensänderung.
- **Grenzen:** OCR ist (wie Redaction) nicht rückgängig machbar — die Ebene
  ist rein zusätzlich; das Einbrennen fragt jetzt auch bei Formen/Markierungen.

## v0.17.12 — Fix: Drehen ohne kurzes „Zurückspringen" in die alte Ansicht
- Nach dem Drehen am Griff erschien die Signatur kurz in der alten Darstellung
  und „drehte sich dann richtig": Das Overlay besitzt eine 120-ms-Blendregel
  für das Hintergrundbild — beim Übernehmen der Drehung blendete das alte,
  ungedrehte Bild über das neue (Bild-für-Bild-Beweis: ein Frame mit halber
  Farbintensität mitten im Wechsel). Die Blendregel ist für den Dreh-Wechsel
  jetzt deaktiviert: Kasten, Bild und Winkel tauschen in einem harten,
  unsichtbaren Schritt.
- Winkel-Eingabe oben: zeigt die Drehung jetzt sofort als Vorschau, während
  der Server rechnet (vorher stand die Signatur ~150 ms im alten Zustand).

## v0.17.11 — Geschützte Signatur: Passwortabfrage direkt beim Ablegen
- Passwortgeschützte Signaturen mussten erst im Menü entsperrt werden, bevor
  sie aufs Papier gezogen werden konnten. Jetzt sind ihre Kacheln **direkt
  ziehbar**: Beim Fallenlassen auf dem Papier erscheint die Passwortfrage —
  mit richtigem Passwort wird die Platzierung sofort fertiggestellt, mit
  falschem bleibt der Dialog offen. (Frisch hochgeladene sind weiterhin
  sofort entsperrt, ohne Doppelabfrage.)

## v0.17.10 — Fix: Signatur-Kachel wieder aufs Papier ziehbar
- Das Ziehen einer Signatur-Kachel aufs Papier verschob stattdessen das ganze
  Fenster: Das Signatur-Panel hängt im Kopfzeilen-Baum, und deren
  Ziehen-Handler (Titelleiste des rahmenlosen Fensters) fing jeden Mausdruck
  aus dem Panel mit. Panel und alle schwebenden Dialoge sind jetzt von der
  Titel-Zieherkennung ausgenommen — Drag & Drop der Kacheln funktioniert
  wieder, die Kopfzeile selbst zieht weiterhin das Fenster.

## v0.17.9 — Signatur beim Hochladen direkt benennen
- Der Upload-Dialog hat ein **Namensfeld** (mit dem Dateinamen vorbelegt):
  Transparenz-Schwellwert, Passwort und jetzt auch der Name lassen sich in
  einem Durchgang festlegen — das nachträgliche Umbenennen entfällt.
  Ungültige Zeichen werden automatisch aus dem Namen entfernt, Enter im
  Namensfeld lädt ebenso hoch wie der Knopf.

## v0.17.8 — Upload-Kachel löst beim Niederdrücken aus (nicht mehr schluckbar)
- Die Nutzer-Aufzeichnungen zeigten: Das Niederdrücken (pointerdown) kam auf
  der Signatur-Kachel **ausnahmslos** an, während Loslassen und Klick-Ereignis
  auf dem betroffenen Notebook systematisch geschluckt wurden. Die Kachel
  „Neue Signatur hochladen" startet den Dateidialog deshalb jetzt schon beim
  Niederdrücken — mit Sperrzeit gegen Doppel-Dialoge. Der restliche Weg
  (Vorschau → Hochladen) war bereits vollständig verifiziert.

## v0.17.7 — Signatur-Kacheln klicken robust (unabhängig vom click-Ereignis)
- Die Aufzeichnung echter Nutzer-Klicks zeigte: Auf den Signatur-Kacheln
  („Neue Signatur hochladen", Kachel-Auswahl) kam Drücken und Bewegen an,
  aber das browser-generierte Klick-Ereignis wurde auf manchen Systemen
  systematisch geschluckt — die Kachel reagierte nie. Sie wirken jetzt auf
  **Drücken + Loslassen** (Zeiger-Ereignisse mit Nahbereich), unabhängig
  davon, ob das System dazwischen eine Auswahl-/Zieherkennung startet.
  Das Ziehen der Kacheln aufs Papier bleibt unverändert.

## v0.17.6 — Fix: Klicks auf Panel-Texte schlagen nicht mehr fehl
- Klicks auf die Beschriftungen im Signatur-Panel (z. B. „Neue Signatur
  hochladen") konnten wirkungslos bleiben: Die Panel-Texte waren
  auswählbar, und ein Klick mit minimaler Mausbewegung startete eine
  Textauswahl — nach einer Auswahl erzeugt Windows kein Klick-Ereignis
  mehr, der Knopf feuerte nie. Panels und Dialoge (Signatur, Umbenennen,
  Mini-Dialoge) sind jetzt nicht mehr textselektierbar; Klicks gehen
  immer als Klicks durch. (Aufzeichnung des Nutzer-Klicks zeigte:
  Drücken+Bewegen kamen an, das Loslassen wurde von der Auswahl geschluckt.)

## v0.17.5 — Originaltext-Editor bricht Zeilen nicht mehr zu früh um
- Das Editierfenster war durch Innenabstand und Rahmen etwas schmaler als der
  Original-Block, und die Bildschirm-Schrift fällt minimal breiter aus als der
  PDF-Satz — jede Zeile brach darum einen Tick früher um, und beim Übernehmen
  wurden aus diesen Sichtumbrüchen echte neue Zeilen („CR am Ende“).
  Die Box ist jetzt so breit wie die **breiteste Originalzeile in genau der
  eingestellten Bildschirm-Schrift** (kanvas-gemessen, + Sicherheitszuschlag):
  Originalzeilen bleiben beim Tippen einzeilig, die Zeilenstruktur beim
  Übernehmen stimmt mit dem Original überein.

## v0.17.4 — Fix: Knöpfe „tun nichts" (Klicks landen versetzt)
- Auf Rechnern mit **Monitor-Mischbetrieb unterschiedlicher Skalierung**
  (z. B. Notebook 150 % + Zweitmonitor anders) landeten echte Mausklicks
  um gut 200 px versetzt in der Seite — „Signatur…", Upload-Kachel usw.
  schienen wirkungslos, obwohl der Code intakt war (programmatische Klicks
  funktionierten; gemessen wurden die Eingaben an der falschen Stelle).
  Ursache: Dem Fenster fehlte die Per-Monitor-DPI-Erkennung (lief nur
  „system-aware"). Der Wrapper ist jetzt **PerMonitorV2** (empfohlene
  Einstellung für WebView2) — Klicks treffen wieder exakt.

## v0.17.3 — Block-Markierung bleibt nach Zeilenersatz erhalten
- Nach dem zeilenweisen Ersetzen (v0.17.2) bekam die neue Zeile eine eigene
  PDF-Blocknummer und leuchtete beim Überfahren nicht mehr mit dem Rest des
  Blocks mit. Die Block-Gruppierung fasst jetzt zusammen, was zusammengehört:
  gleicher PDF-Block **oder** gleiche Zeile (y-Überlappung) — ersetzte
  Tabellen-Zeilen (Betrag/Datum) bleiben optisch Teil ihres Blocks, wie vor
  der Bearbeitung.

## v0.17.2 — Tabellen/Spalten beim Bearbeiten nicht mehr zerstört
- Mehrfach-Auswahlen mit **Spalteninhalt** (Datum links, Beschreibung Mitte,
  Betrag rechts sind im PDF eigene Zeilen auf gleicher Höhe) wurden beim
  Übernehmen zu einem fließenden Textblock zusammengezogen — das Spaltenlayout
  war hinüber. Jetzt erkennt Blattwerk überlappende Zeilen und ersetzt
  **zeilenweise an der jeweiligen Originalposition**: Unveränderte Zeilen
  bleiben völlig unberührt, geänderte landen exakt dort, wo ihre Originalzeile
  lag (Spalten-x und Zeilen-y). Absatz-Blöcke (Zeilen untereinander) nutzen
  weiterhin das verschiebbare Sammelobjekt mit erhaltenem Zeilenraster.

## v0.17.1 — Originaltext-Editor voll deckend (Doppeltext sicher ausgeschlossen)
- Der deckende Hintergrund des Originaltext-Editors (v0.17.0) war mit 96 %
  fast deckend — Restdurchschein des alten Texts ist jetzt sicher
  ausgeschlossen (voll opak). Hinweis: Die Ansicht zeigt den Fix erst nach
  einem App-Neustart.

## v0.17.0 — Mehrzeiligen Originaltext positionsgetreu bearbeiten
- **Zeilenpositionen bleiben erhalten:** Beim Bearbeiten mehrzeiliger
  Originaltexte (Block-Doppelklick oder Umschalt+Klick-Sammlung) übernimmt der
  neue Text jetzt die **Baseline der ersten Zeile und den gemessenen
  Zeilenabstand** des Originals — nicht mehr das starre 1,25-fache Raster.
  Unveränderte Zeilen stehen nach dem Übernehmen auf Zehntel-Punkt exakt dort,
  wo das Original stand; auch im gespeicherten PDF (Zeilenabstand wird im
  NM-Marker geführt und gilt für Overlay, Appearance, Verschieben und Undo).
- **Originaltext-Editor deckend:** Unter dem Eingabefeld steht beim
  Originaltext der alte Text noch im Papier — das Feld hat deshalb jetzt einen
  deckenden Papier-Hintergrund (vorher durchscheinend: „Buchstabenwald").
  Neu eingetippter Text bleibt wie gewohnt transparent.
- Längere Zeilen erweitern das Textobjekt jetzt nach Bedarf in der Breite
  (zuvor wurde längerer Text an der Original-Blockbreite abgeschnitten).

## v0.16.10 — Fix: weiße Striche im Fensterrand nach dem Vergrößern weg
- Beim Ziehen der Fensterkante blieben stellenweise kleine weiße vertikale
  Striche in der Verlaufszone stehen (das WebView2 malt während der
  Größenänderung kurz über die Randzone, bevor die Form sie wieder
  übermalt). Der Rand wird jetzt nach jedem Größenänderungsschritt
  vollständig neu gezeichnet — sofort und nochmals nach dem Layout
  (mit Handle-Schutz, sonst wäre die App beim Start weggeworfen worden).

## v0.16.9 — Schwarz-Rot-Gold-Rand jetzt in beiden Designs
- Der Verlaufsrand (nahtloser Umlauf, v0.16.7) gehört nicht mehr nur zum
  hellen Design — konsequenterweise trägt ihn jetzt auch das dunkle.
  Maximiert bleibt das Fenster randlos wie gehabt.

## v0.16.8 — Design-Knopf fix oben rechts neben den Fenstertasten
- Der Design-Umschalter (Sonne/Mond) wanderte beim Umbrechen der Leiste mit
  in Folgezeilen. Er sitzt jetzt in der fixen Zone der ersten Zeile, direkt
  links neben Minimieren — bei jeder Fensterbreite. Der Leisteninhalt hält
  rechts entsprechend mehr Abstand.

## v0.16.7 — Rand-Verlauf als nahtloser Umlauf
- Der Schwarz-Rot-Gold-Verlauf lief je Seite einzeln und sprang an zwei Ecken
  von Gold auf Schwarz. Jetzt läuft er als geschlossener Umlauf ums Fenster:
  oben schwarz→gold, rechts gold→schwarz, unten (weiter im Uhrzeigersinn)
  schwarz→gold, links gold→schwarz — an jeder Ecke treffen gleiche Farben
  aufeinander, kein Sprung mehr.

## v0.16.6 — Heller Fensterrand: Schwarz-Rot-Gold statt Schwarz
- Im hellen Design war der Fensterrand komplett schwarz — hart am hellen
  Fenster. Jetzt zeigt er dort den Marken-Verlauf **Schwarz → Rot → Gold**
  (wie Icon und Kopfzeilen-Band), rundum auf allen vier Seiten. Im dunklen
  Design bleibt der Rand dunkel wie bisher.
- Die UI meldet dem Fenster beim Start und bei jedem Designwechsel den
  Theme-Zustand (`theme|light/dark` über den WebView2-Kanal); maximiert
  bleibt das Fenster randlos.

## v0.16.5 — Fensterrand rundum: oben geschlossen (und greifbar)
- Der dunkle Fensterrand lief bisher nur unten/links/rechts — oben endete das
  Fenster unsichtbar an der Bildschirmkante. Jetzt zieht sich die 6px-Leiste
  rundum, auch über der Kopfzeile: Das Fenster ist oben klar abgegrenzt.
- Die obere Kante ist zugleich Größengriff (wie unten/links/rechts): Ziehen
  verändert die Fensterhöhe; die Ecken oben-links/oben-rechts ändern die
  Größe diagonal. Maximiert bleibt das Fenster randlos über dem Bildschirm.

## v0.16.4 — Fenstertasten IMMER oben rechts (auch bei Umbruch)
- Die Tasten Minimieren/Maximieren/Schließen wanderten bei engen Fenstern
  mit in die zweite Kopfzeilenzeile. Jetzt sind sie absolut oben rechts
  verankert: Sie bleiben IMMER in der ersten Zeile, während der Rest der
  Leiste bei Bedarf in Folgezeilen umbricht (die Tastenzone bleibt rechts
  immer frei — kein Element läuft unter die Tasten).
- Die Stufen der Leiste (Beschriftungen aus → Marke schlank → zweite Reihe)
  wirken unverändert, messen aber jetzt den Inhaltsstreifen.

## v0.16.3 — Block-Editor: Undo stellt jede Zeile exakt wieder her
- Nach der Block-Bearbeitung (v0.15.0) hingen die Zeilen nur als ein Objekt
  zusammen, und Undo setzte den gesamten Text an die Position der ersten
  Zeile. Jetzt tilgt der Server alle beteiligten Zeilen in einem Zug
  (`/api/text/blockreplace`) — der EINE Undo-Eintrag („origzeilen") stellt
  **JEDE Zeile an ihrer eigenen alten Position** wieder her: erst Strg+Z
  nimmt das neue Textobjekt weg, das zweite Strg+Z holt alle Originalzeilen
  unverrückt zurück. Die Zeilen-Rückrestoration nutzt die exakte Basislinie
  aus dem Dokument (neuer Helfer `_zeile_in_rect`), nicht die einer
  Nachbarzeile (dort irrte die alte Spannensuche bei engem Zeilenabstand).
- Der Entfernen-Knopf im Editor geht denselben Weg (alle Zeilen, ein Undo).
- **Mehrzeilige Textobjekte stimmen jetzt mit dem gespeicherten PDF überein:**
  MuPDFs eigenes Freitext-Aussehen rendert Zeilen mit ~2,4-fachem Abstand und
  schneidet Folgelinien an der Box ab (4. Zeile war nach dem Speichern weg).
  Blattwerk setzt deshalb IMMER seinen eigenen Appearance-Stream (1,25-faches
  Leading, Baseline wie das Overlay) — nicht mehr nur bei Zeichenabstand.
- **Doppel-Commit gebunden:** Das Übernehmen mit Enter entfernte die Textarea,
  deren blur-Handler startete den Commit sofort ein zweites Mal (Rennen:
  verschwundene Annotationen, doppelte Redactions). Der Editor-Status wird
  jetzt entzogen, bevor DOM-Knoten entfernt werden — gilt auch für den
  Neutext-Editor.
- Mehrzeilige Textobjekte zeigen ihre Zeilenumbrüche jetzt auch als Overlay.
- Bekannt (bestehendes Verhalten, nicht neu): Redaction arbeitet wortgenau —
  bei einzeln gesammelten Zeilen mit weniger als ~1,3 Zeilenabstand kann eine
  dazwischenliegende Nachbarspalte mit entfernt werden (gilt seit v0.12 für
  Einzeledits genauso). Ganze Blöcke sind nicht betroffen.

## v0.16.2 — Fenstertasten sticky: bleiben bei schmalen Fenstern immer oben rechts sichtbar (opake Fläche)
## v0.16.1 — Kopfzeile höher mit Logo/Name zurück und Grifffunken als sichtbare Zieh-Zonen; Fenstertasten rechts
## v0.16.0 — Rahmenloses Fenster: Kopfzeile als Titelleiste (Ziehen/Doppelklick-Max), Fenstertasten min/max/zu über Wrapper-PostMessage, Resize-Ränder per WM_NCHITTEST, taskbar-sicheres MaximizedBounds

## v0.15.0 — Textblöcke: Hover, Block-Editor, Zeilen sammeln
- **Block- Hover:** Originaltext-Zeilen werden serverseitig zu Blöcken gruppiert
  (Absätze) — fährt man mit der Maus über eine Zeile, leuchtet der ganze Block.
- **Doppelklick bearbeitet den ganzen Block:** Der Editor öffnet mit allen Zeilen
  des Blocks als mehrzeiligem Text; nach dem Übernehmen ist der ganze Block ein
  verschiebbares Objekt (Schrift, Größe, Farbe, Abstand wie gewohnt änderbar).
- **Umschalt+Klick sammelt Zeilen:** Mehrere einzelne Zeilen markieren und dann
  per Doppelklick auf eine der Markierten gemeinsam bearbeiten.
- Server: `/api/text` liefert je Zeile die Blocknummer (`b`, aus PyMuPDF-Blocks).

## v0.14.7 — Bedienung: Mausrad für Größe/Abstand, bequeme Exits im Text-Modus
- **Mausrad über den Feldern „Schriftgröße" und „Zeichenabstand"** ändert die
  Werte (± 1 bzw. ± 0,25) — ohne das Feld anzuklicken; wirkt live auf Editor
  und ausgewählte Texte.
- **Text-Modus beenden:** Rechtsklick auf die Seite, Esc (schließt den Editor
  mit) oder Klick neben ein offenes Textfeld — zusätzlich zu T/Auswahl.
  Esc im Originaltext-Editor verwirft weiterhin die Änderung und beendet.
- Der Freitext-Editor selbst erlaubt weiter Mehrzeilentippen über Enter
  (Commit nur über Strg+Enter oder Klick neben dem Feld).

## v0.14.6 — Editier-Feld transparent: Hintergrund beim Tippen sehen
- Das Eingabefeld (neuer Text wie Originaltext-Editor) ist jetzt **transparent** —
  beim Tippen sieht man das Papier bzw. das Formular darunter und kann Text,
  Position und Zeichenabstand direkt daran ausrichten. Der gestrichelte Rahmen
  markiert weiter den Bearbeitungsbereich.

## v0.14.5 — Fix: Schriftänderung wirkt jetzt auf angeklickte Texte (und Fett/Kursiv überall)
- **Die Werkzeugleiste wirkt live auf angeklickte Text-Annotationen:** Text
  anklicken, Schrift/Familie/Stil/Größe/Farbe/Abstand oben ändern — sofort
  übernommen, Selektion bleibt erhalten. Vorher reagierte die Leiste nur während
  des Editors (und ein Klick in die Leiste schloss den Doppelklick-Editor nicht).
- **Fix: Fett/Kursiv bei Times und Courier schlug still auf Helvetica zurück** —
  die Alias-Bildung 'tirob'/'courb' war ungültig (richtig: tibo/cobo); jetzt
  systematische Alias-Tabelle im Client und Rück-Aufsplitten beim Editor-Öffnen
  (Fett-Texte zeigen Familie+Stil korrekt in der Leiste).
- Der Editor-Pfad (Doppelklick) bleibt unverändert; auch dort gilt die
  korrekte Alias-Bildung jetzt beim Übernehmen.

## v0.14.4 — Zeichenabstand (Spacing) für Text
- **Neues Werkzeugleisten-Feld „Zeichenabstand"** (Punkte, auch negativ für
  engere Texte): wirkt live in der Editor-Vorschau und auf neue und bearbeitete
  Text-Annotationen.
- Umsetzung: bei Spacing ≠ 0 erzeugt der Server einen eigenen Appearance-Stream
  für die Annotation (PDF-Operator `Tc`); der Spacing-Wert wandert in den
  NM-Marker (5. Feld) und bleibt damit bei Verschieben, Bearbeiten, Undo und
  „Speichern unter" erhalten.
- **Einbrennen:** Gespacete Freitexte werden vor dem Einbrennen zeichenweise als
  echter Seiteninhalt eingesetzt (Zeichenabstand bleibt exakt erhalten), danach
  wie üblich gebaked.

## v0.14.3 — Eingebettete Bilder verschieben
- **Grafiken im PDF bewegen:** Eingebettete Bilder (Logos, Fotos) werden im
  normalen Modus als greifbare Objekte angezeigt (gestrichelter Rahmen beim
  Hovern) — anklicken, ziehen, fertig. Die alte Stelle wird weiß überdeckt, das
  Bild an der neuen Stelle wieder eingesetzt (gleiche eingebettete Grafik per
  xref, keine Re-Qualitätseinbuße). Strg+Z schiebt zurück.
- Neue Endpunkte: `/api/imageinfo` (Platzierungen je Seite) und `/api/image/move`.
  Ganzseitenbilder (Scans) und Inline-Bilder bleiben bewusst fix.
- Grenzen: Die alte Bildstelle bleibt in der Datei erhalten (nur weiß überdeckt);
  bei erneutem Verschieben nach Neuladen wird die neue Platzierung gegriffen.

## v0.14.2 — Text-Modus: Bereich aufziehen statt nur Punkt klicken
- **Mit gedrückter Maustaste den Textbereich aufziehen:** Im Text-Modus zeichnet
  man jetzt den Kasten für den neuen Text direkt auf (Rahmen wie bei der
  Freihand-Auswahl); der Editor öffnet sich exakt in diesem Bereich, und die
  Annotation übernimmt die aufgezogene Größe (WYSIWYG — bei längerem Text wächst
  der Kasten noch mit). Der Editor schrumpft beim Tippen nicht mehr auf eine
  Zeile zusammen.
- Ein stiller Klick behält das bisherige Verhalten (Standard-Kasten an der
  Klickstelle, Breite passt sich dem Text an).

## v0.14.1 — Originaltext-Editor: Schrift erreichbar, Text verschiebbar
- **Fix:** Ein Klick in die Schrift-Werkzeuge hat den Editor sofort committet und
  geschlossen (Blur-Committ ohne Ausnahme für die Werkzeugleiste) — deshalb wirkte
  Schriftänderung „unmöglich". Jetzt bleibt der Editor offen, solange in der
  Leiste gearbeitet wird (wie beim Freitext-Editor).
- **Der geänderte Text wird jetzt zum verschiebbaren Objekt:** Nach dem Übernehmen
  wird die Originalzeile wegredigiert und der neue Text als Freitext-Annotation
  an derselben Stelle angelegt — greifen & ziehen, Schrift/Größe/Farbe später per
  Doppelklick änderbar, Einbrennen beim Speichern wie bei jeder Annotation.
  Strg+Z nimmt die Änderung mehrschrittig zurück (Objekt weg, Originalzeile zurück).
- Reines Entfernen (Löschen im Editor) bleibt echte Redaction ohne Objekt.

## v0.14.0 — Die App heißt jetzt **Blattwerk**
- Umbenennung an allen sichtbaren Stellen: Fenstertitel und Taskbar („Blattwerk –
  Datei.pdf"), Splash-Screen, Kopfzeile, HTML-Titel, Demodokument
  („Blattwerk Demo-Dokument"), Fehler- und Hinweisdialoge, FastAPI-Titel.
- Technische Namen bleiben unverändert (Exe PdfWerkstatt.exe /
  PdfWerkstattServer.exe, Projektordner pdf-werkstatt, Dateizuordnung und
  Deploy-Pfade funktionieren weiter wie gehabt).
- Vollswap-Deployment nötig, da der Wrapper (Fenstertitel) geändert wurde;
  Einstellungen, Fensterlage und Signatur-Ordner wurden gesichert und
  zurückgespielt. Demodokument wird beim nächsten Start mit neuem Titel erzeugt.
- Namensfindung: „Blattwerk" = Blatt (PDF-Seite) + Werk; im PDF-Markt
  kollisionsfrei (Nutzerentscheidung aus 3 Kandidaten).

## v0.13.4 — Dark Theme: dunkles Grau + weiche Flaggen-Verlaufskante
- Rückmeldung umgesetzt: Der Dark-Theme-Grundton ist wieder **dunkles Grau**
  (statt fast Schwarz) — damit heben sich schwarze Elemente sichtbar ab.
- Die Schwarz-Rot-Gold-Kante der Kopfzeile verläuft jetzt als **weicher
  Farbverlauf** (Schwarz → Rot → Gold) statt in harten Dritteln.

## v0.13.3 — Dark Theme in Schwarz-Rot-Gold
- **Nationalfarben im Dark Theme:** tiefschwarze Flächen (Dokumentbereich,
  Kopfzeile, Panels), **Gold** als Akzentfarbe (aktives Werkzeug, Pill,
  Auswahlrahmen, Auswahlfeld-Ränder, Slider, primäre Dialogknöpfe), **Rot** für
  Gefahr/Löschen. Dazu eine dezente Schwarz-Rot-Gold-Kante an der Oberkante der
  Kopfzeile.
- Die Auswahl- und Fokusfarben (Freihand-Auswahl, Zeilenmarkierung, Textfelder)
  sind jetzt themengesteuert: Dark = Gold, Light = unverändert Blau. Das Light
  Theme bleibt komplett, wie es war.

## v0.13.2 — Fix: eingebrannte Signatur bleibt nach dem Speichern sichtbar
- Beim Speichern mit Einbrennen verschwand die Signatur optisch aus der Ansicht:
  die Overlays wurden entfernt, aber das Seitenbild stammte noch von vor dem
  Einbrennen. Erst das Neuladen des Dokuments zeigte sie wieder.
- Jetzt liefert `/api/save` die betroffenen Seiten mit (Seiten mit Annotationen
  vor dem Einbrennen), und die UI lädt genau diese Seitenbilder neu — die
  eingebrannte Signatur ist sofort sichtbar. „Speichern unter" mit Einbrennen
  aktualisiert die Seiten mit Overlays ebenfalls (Wrapper-Pfad).

## v0.13.1 — Fix: Modus-Pill sitzt exakt, auch nach Größenwechseln
- Die gleitende Werkzeug-Pill war vertikal statisch verankert und maß ihre
  Position nur einmal — sobald die Knopfbeschriftungen verschwanden (schmales
  Fenster), saß sie verschoben und in alter Größe. Jetzt: vertikale Position
  dynamisch, und die drei Modus-Knöpfe werden per ResizeObserver beobachtet —
  die Pill folgt jeder Größenänderung pixelgenau.

## v0.13.0 — Motion: die App bewegt sich (alle Stufen des Motion-Konzepts)
- **Fundament:** Motion-Tokens (Dauern 120/180/260/380 ms, Kurven standard/in/out/
  pop) als CSS-Variablen; `prefers-reduced-motion` schaltet alles ab; Knöpfe
  federn beim Drücken (scale .96); Dialoge und das Signatur-Menü wachsen aus
  ihrer Knopfposition, Kacheln staggern hinein; Kachel-Hover hebt an.
- **Lebendiges Dokument:** Seitenwechsel scrollen weich statt zu springen; das
  Scharfstellen nach dem Zoom crossfaded statt hart zu tauschen; platzierte
  Signaturen poppen, gelöschte verblassen; Thumbnails und Dokumentseiten
  staggern beim Öffnen ein; Thumbnails heben sich beim Hover; Treffer zählen
  und pulsieren; der Copy-Chip poppt.
- **Signature Moments:** der aktive Werkzeughintergrund **gleitet als Pill**
  zwischen Auswahl/Text/Löschen; nach erfolgreichem Speichern **stempelt** ein
  Häkchen auf den Speichern-Knopf; Hell/Dunkel wechselt als **wachsender Kreis**
  vom Theme-Knopf aus (View Transitions API, Feature-Detect); Statusmeldungen
  mit Erfolgshäkchen; Löschen-ausführen slidet in die Fußleiste; Rückgängig-
  Icon dreht kurz rückwärts.
- Konzept: `MOTION-KONZEPT.md` (Tokens, Inventar, Regeln — u. a. nur transform/
  opacity animieren, nichts länger als 500 ms, Reduced Motion respektieren).

## v0.12.10 — Originaltext-Editor: neue Zeilen und Schriftwechsel
- **Umschalt+Enter fügt eine neue Zeile ein** (Enter übernimmt weiterhin sofort).
  Der ersetzte Text wird mehrzeilig als echter Seiteninhalt eingesetzt, Folgezeilen
  rücken entsprechend tiefer; auch Strg+Z stellt mehrzeilig zurück.
- **Schrift änderbar:** Die Werkzeugleiste (Familie, Stil, Größe, Farbe) ist mit
  dem Originaltext-Editor verbunden — sie zeigt beim Öffnen die ermittelte Schrift
  der Zeile und übernimmt Änderungen sofort in Vorschau und Ergebnis.
- Server: `/api/text/replace` nimmt optional `size`/`font`/`color` (Übersteuerung
  der Zeilenschrift) und setzt mehrzeiligen Text; Undo berücksichtigt die Zeilen.

## v0.12.9 — Signatur-Upload mit Vorschau und Transparenz-Regler
- **Vorschaudialog beim Hochladen:** Bild gewählt → Dialog mit Titel, Vorschau
  auf **Schachbrettmuster** (wie aus Bildprogrammen bekannt — das Muster zeigt,
  wo der Hintergrund entfernt wurde), Passwortfeld und Schwellwert-Regler.
- **Transparenz einstellbar:** Der Regler (0–255, Standard 232, 0 = aus) steuert,
  ab welcher Helligkeit Weiß durchsichtig wird. Die Vorschau rechnet live und
  immer vom Originalbild neu; der Upload übernimmt exakt den eingestellten Wert.
  Serverseitig nimmt `/api/signature/upload` dafür den Parameter `threshold`.

## v0.12.8 — Symbolleiste schlanker: Signatur-Klickmodus entfällt
- Der Werkzeugknopf „Signatur" (Klick-Platzierung) ist entfernt — Signaturen
  werden ausschließlich per **Drag & Drop aus dem „Signatur…"-Menü** aufs Papier
  gezogen (seit v0.12.5). Die Leiste zeigt jetzt: Auswahl · Text · Löschen.
- Der Signatur-Menü-Knopf behält seine Verwaltungsfunktion (Hochladen,
  Umbenennen, Passwort, Löschen, Vorschau). Kurzhilfe und Tooltip angepasst.

## v0.12.7 — Signatur-Menü: Passwort beim Hochladen & Schloss-Knopf
- **Passwort direkt beim Hochladen:** Nach der Bildauswahl erscheint im Menü
  eine Zeile mit Passwortfeld und „Hochladen" — wer will, verschlüsselt die neue
  Signatur sofort. Das lose Passwortfeld am Menüende ist entfallen.
- **Schloss-Knopf an jeder Kachel** (neben Umbenennen/Löschen): Passwort
  nachträglich setzen, ändern oder – bei leerem Feld – den Schutz entfernen. Der
  Server verschlüsselt die Signatur um bzw. legt sie wieder ungeschützt ab;
  bestehende Platzierungen folgen dem neuen Dateinamen. Gesperrte Kacheln
  führen zunächst zum Entsperren-Dialog.
- Fix: Klicks in den schwebenden Dialogen (Entsperren/Passwort/Umbenennen)
  schlossen das Signatur-Menü im Hintergrund und ließen dessen Kacheln veraltet.

## v0.12.6 — Griff der Seitenleiste wandert mit
- Fix: Beim Verschieben der Lesezeichen-Leiste auf die linke Seite blieb der
  Ein-/Ausklapp-Griff fälschlich am rechten Fensterrand (in v0.12.3 war nur der
  Leiste selbst die neue Position zugewiesen worden, nicht dem Griff). Jetzt
  sitzt der Griff immer direkt zwischen Leiste und Dokument.

## v0.12.5 — Signaturen per Drag & Drop aufs Papier ziehen
- **Direkt aus der Liste ziehen:** Kachel im „Signatur…"-Menü anfassen, aufs
  Dokument ziehen, loslassen — die Signatur landet genau an der Stelle (das
  Papier leuchtet beim Darüberziehen auf, danach wie üblich greifen & ziehen).
  Klicken zum Auswählen funktioniert wie bisher.
- **Passwort-Logik verständlich gemacht:** Das Passwortfeld im Menü verschlüsselt
  die als nächstes hochgeladene Signatur (Schloss-Symbol). Gesperrte Kacheln sind
  erst nach dem Entsperren auswählbar und ziehbar; Entsperren gilt bis
  Programmende. Hinweiszeile im Menü erklärt den Ablauf.
- Kurzhilfe aktualisiert.

## v0.12.4 — „Auswahl"-Knopf: Modus verlassen, gesetzten Text verschieben
- Neuer Knopf **„Auswahl" (Mauszeiger-Symbol)** links neben „Signatur": Er kehrt
  aus dem Text-/Löschen-/Signatur-Modus in den normalen Modus zurück (geht
  weiterhin auch mit Esc). Das aktive Werkzeug ist in der Leiste hervorgehoben —
  inklusive „Auswahl" als Startzustand.
- **Nach dem Setzen eines Textes kehrt die App automatisch in den Auswahl-Modus
  zurück** (wie bei Signaturen schon üblich). Der neue Text ist damit sofort
  greifbar und verschiebbar — vorher blieb der Text-Modus aktiv und der
  Verschiebe-Cursor log (Ziehen tat nichts). Wer mehrere Texte hintereinander
  platziert, bleibt durch Klick aufs Papier im Text-Modus.
- Der Vier-Pfeil-Cursor auf Signaturen/Texten erscheint nur noch, wenn sie auch
  wirklich verschiebbar sind (im Text-/Signatur-Modus kein falscher Hinweis).

## v0.12.3 — Seitenvorschau: einklappen und Seite wählen
- Die Seitenvorschau lässt sich jetzt wie die Lesezeichen-Leiste **am Rand ein-
  und ausklappen** (neuer Griff neben der Spalte; der „Seiten"-Knopf unten wirkt
  weiterhin, beide steuern denselben Zustand).
- **Beide Bereiche sind frei positionierbar:** Seitenvorschau und Lesezeichen-
  Leiste haben je einen Pfeilknopf („auf die andere Seite verschieben") — so sind
  z. B. beide Bereiche links oder beide rechts möglich. Auch das wird gespeichert
  (wie Theme und Einklapp-Zustand, über `/api/prefs`).
- Technik: Layout über flex-`order` statt `row-reverse` (dafür waren die Bereiche
  zwangsläufig auf gegenüberliegenden Seiten). Alte Einstellung „Seitenleiste
  links" wird beim ersten Start automatisch auf das neue Modell übertragen.

## v0.12.2 — Ziehen verschiebt die Seite, Kopieren per Alt+Ziehen
- **Ziehen mit der Maustaste auf dem Papier schiebt jetzt die Ansicht** (Pan,
  Hand-Cursor beim Ziehen) — vorher wurde dabei die Kopier-Auswahl aufgezogen.
- Die Freihand-Textauswahl gibt es weiterhin, per **Alt+Ziehen**. Unverändert:
  einzelne Zeile anklicken kopiert, Strg+Klick hängt an, Doppelklick editiert
  den Originaltext.
- Nur im normalen Modus (Signatur-/Text-/Löschen-Modus arbeiten wie bisher).
  Kurzhilfe aktualisiert.

## v0.12.1 — Zoom hält den Mauspunkt fest
- **Strg+Mausrad zoomt auf den Punkt unterm Cursor** (vorher lief das Bild immer
  zur oberen linken Ecke der Seite). Nach dem Zoom bleibt derselbe Dokumentpunkt
  unter der Maus — rein- und rauszoomend, horizontal wie vertikal.
- Die +/−-Knöpfe der Zoomleiste zoomen jetzt auf die **Bildschirmmitte** statt
  zur Seitenoberkante (wie Browser/Word).
- Am Zoomlimit (30–400 %) ruckt es nicht mehr: überschüssige Radschläge
  verschieben die Ansicht nicht (vorher konnte der Anker-Ausgleich scrollen).
- Technik: `applyZoom` nimmt optional einen Fokus (Seite unterm Punkt + Anteil
  rx/ry); die Scroll-Korrektur läuft gebündelt in einem rAF, bei schnellen
  Radschlägen gewinnt der letzte Anker.

## v0.12 — Originaltext editieren (wie PDFgear, nur echter Text)
- **Doppelklick auf eine Textzeile** (echter Text, kein Scan-Bild) öffnet ein
  Eingabefeld direkt über dem Text, mit übernommener Schriftgröße/-farbe/-art
  (Helvetica/Times/Courier + Fett/Kursiv aus der dominanten Textspanne).
- Enter übernimmt: Originaltext wird an der Stelle entfernt (Redaction), der neue
  als echter Seiteninhalt mit gleicher Basislinie eingesetzt. Leerer Text/der rote
  Knopf = Originaltext entfernen. Strg+Z stellt den Originaltext zurück.
- Einzelklick kopiert weiterhin (Doppelklick kopiert nicht mehr aus Versehen);
  /api/textspan liefert die Schriftdaten für die Vorschau. Suite +5 Checks (47).

## v0.11.5 — Auswahlrechteck verschwindet beim Loslassen
- Fix: Das blaue Auswahlrechteck blieb nach dem Kopieren stehen und sammelte sich
  bei jedem weiteren Zug an (es wurde nie entfernt und wanderte beim Zoomen nicht
  mit). Jetzt wird es beim Loslassen entfernt; Sicherheitsnetz in clearFreeSel und
  beim Seiten-Neuaufbau. Beim Ziehen ist es weiterhin sichtbar.

## v0.11.4 — Knopf „Kopie herunterladen" entfernt, Auswahl-Hinweise
- „Kopie herunterladen" (Überbleibsel vor „Speichern unter") aus der Kopfzeile entfernt.
- Zieht man eine Text-Auswahl über einen Bereich ohne erkannten Text, sagt die
  Statusleiste jetzt „Kein Text in der Auswahl…" (vorher geschah sichtbar nichts).
- Kurzhilfe ergänzt: Kopieren per Aufziehen oder Zeilen-Klick.

## v0.11.3 — Freihand-Auswahl startet auf Textblöcken
- Fix: Das Aufziehen der Textauswahl startete nur auf „leerem Papier" — bei OCR-Seiten
  liegt aber fast überall ein Textblock-Overlay, also traf der Start fast immer einen
  Block und die Auswahl erschien nie (übrig blieb der Einzelklick pro OCR-Block).
  Jetzt startet das Aufziehen auch direkt auf Textblöcken; der Einzelklick kopiert
  weiterhin eine Zeile, Strg+Klick hängt an.

## v0.11.2 — Drehen ohne Springer
- Fix: Nach dem Drehen am Griff flippte die Signatur kurz auf die alte Darstellung
  zurück, bevor die neue kam. Jetzt bleibt die Live-Drehung bis zum Abschluss stehen;
  das gedrehte Bild wird vorab geladen und Kasten/Bild/Daten in einem Rutsch am
  vorhandenen Overlay ausgetauscht (kein Neuaufbau, kein Flackern — auch beim
  Winkelfeld und der 90°-Aktion).

## v0.11.1 — Drehgriff am Rahmen + Funktionsleisten-Start-Fix
- **Direkt drehen:** Runder Griff über der ausgewählten Signatur — daran ziehen dreht
  live (Rahmen dreht mit); Umschalt-Taste rastet auf 15°-Schritte, der Winkel wird
  während des Ziehens angezeigt. Winkelfeld bleibt für exakte Werte.
- Fix (Toolbar): Beim Start zeigte die Funktionsleiste nicht alles und brach erst nach
  manueller Fenstergrößenänderung um. Ursache: Breitenänderungen NACH dem Laden
  (Signatur-Vorschau im Knopf, Schriftart-Wechsel) erwischen die fixen Timeouts.
  Jetzt ereignisbasiert nachgeführt (ResizeObserver, load, document.fonts.ready,
  Vorschaubild-Load).

## v0.11 — Signaturen in beliebigen Winkeln drehen
- Winkel-Feld in der Eigenschaftsleiste (nur bei Signatur): Zielwinkel in Grad frei
  eingeben (positive Winkel = im Uhrzeigersinn). Rechtsklick → „Drehen (90°)" dreht
  wie bisher als Schnellaktion weiter.
- Der Server dreht das Bild IMMER vom Original aus um den Gesamtwinkel (keine
  Qualitätsverluste bei wiederholtem Drehen, kein Aufblähen durch Kaskadierung);
  der Auswahl-Kasten wird auf die gedrehte Hülle skaliert — die Signatur behält
  ihre Größe, der Kasten wächst nur um die schrägen Ecken.
- Overlay-Ansicht und eingebettetes PDF-Bild sind identisch (serverseitig gedrehte
  Vorschau über /api/signature/file?rot=…). Undo dreht zurück. Suite um freie
  Winkel erweitert (42 Checks).

## v0.10.3 — Einbrennen auch bei „Speichern unter"
- Fix: Die Einbrennen-Abfrage kam nur beim normalen „Speichern" — „Speichern unter"
  schrieb immer bewegliche Annotationen. Jetzt dieselbe Abfrage (bzw. direktes
  Speichern ohne Objekte) auch dort; Server: /api/saveas?flatten=1.
- Die Checkbox „Auswahl merken" ist entfallen: Wer einmal „beweglich + merken" gewählt
  hatte, kam nie wieder zur Einbrennen-Frage. Der Dialog erscheint jetzt bei jedem
  Speichern/Speichern-unter, sobald bewegliche Objekte vorhanden sind.
- Statusmeldungen präzisiert: „Gespeichert (eingebrannt)" bzw.
  „Gespeichert (beweglich) – Signaturen/Texte bleiben änderbar".
- Datei-Beweis geführt (frisch geöffnete PDFs): flatten=1 → Signatur im Seiteninhalt,
  keine Annotationen; flatten=0 → Annotation mit eingebettetem Bild in der Datei.

## v0.10.2 — „Speichern unter" wechselt das Arbeitsdokument
- Fix (UX): Nach „Speichern unter" blieb die Änderungsmarkierung stehen — beim Beenden
  kam die Warnung „nicht gespeicherte Änderungen", obwohl gerade gespeichert wurde.
  Jetzt wie üblich (Word & Co.): Die neue Datei wird das Arbeitsdokument — Warnung
  entfällt, Strg+S und Speichern-beim-Schließen schreiben die neue Datei, Statusleiste
  meldet den Wechsel. Server öffnet das Dokument nach dem Kopieren neu (ohne garbage,
  damit Undo-Referenzen stabil bleiben); Annotationen/Undo bleiben nutzbar.

## v0.10.1 — Logo im Startbildschirm
- Startbildschirm und Fehlerbildschirm zeigen das App-Logo (Base64 aus der
  Server-Instanz `server\_internal\static\logo.png`, Fallback: Entwicklungspfad bzw. Symbol)

## v0.10 — Speichern unter, Drehen, Einbrennen, Passwort-Signaturen
- **Speichern unter**: Toolbar-Knopf, Systemdialog (Wrapper), Kopie inkl. aller Änderungen
  über `/api/saveas`; Meldung per Skript-Rückkanal in die Statusleiste
- **Signatur drehen**: Rechtsklick → „Drehen (90°)", beliebig oft; Rect tauscht um das
  Zentrum, Bild wird vorgedreht neu eingebettet (NM-Marker führt den Winkel mit);
  Strg+Z dreht zurück. Neu anlegen statt AP-Tausch geht nicht: add_stamp_annot
  normalisiert das Rect (neue PyMuPDF-Falle, in AGENTS.md dokumentiert)
- **Einbrennen beim Speichern**: Speichern fragt (falls bewegliche Objekte da sind):
  „Einbrennen & speichern" (Signatur/Texte werden fixer Seiteninhalt, in keinem PDF-Programm
  mehr entfernbar; Formularfelder bleiben ausfüllbar) oder „Beweglich speichern".
  Auswahl merkbar (Einstellung `flatten`). Server: `bake(widgets=False)`
- **Passwortgeschützte Signaturen**: Beim Hochladen optionales Passwort → Datei liegt
  als `.pwdsig` AES-verschlüsselt (Fernet + PBKDF2-SHA256, 200k Iterationen) — im
  Gegensatz zu PDFgear ist die Signatur auf der Festplatte nicht mehr auslesbar.
  Passwort gilt bis Programmende (RAM), wird nie gespeichert. Galerie zeigt Schloss,
  Entsperr-Dialog mit Fehlermeldung bei falschem Passwort. Nach Serverneustart wieder
  gesperrt. Löschen/Umbenennen ohne Passwort möglich (Dateiname, nicht Inhalt)
- Fix (mitgefunden): Kopfzeilen-Knöpfe „Kopie herunterladen" und „Drucken" waren seit
  der Toolbar-Umstellung deaktiviert
- Neues Signatur-Icon (Unterschriftszug statt Stift)
- Suite um 8 Checks erweitert (33 gesamt): Speichern unter, Drehen+Undo, Einbrennen,
  verschlüsselte Ablage, Sperrzustand nach Neustart

## v0.9 — Einstellungen & Fenster bleiben gespeichert
- Fix: Einstellungen (Theme, Seitenleiste links/rechts + ein-/ausgeklappt, Miniaturen)
  überlebten den Neustart nicht — localStorage ist pro Server-Port, und der Port wechselt
  bei jedem Programmstart. Jetzt: `/api/prefs` (GET/POST) speichert in
  `PDF-Werkstatt\einstellungen.json` (neben der EXE, überlebt Server-Updates).
- Neu: Fensterposition, -größe und Maximiert-Zustand werden beim Schließen in `fenster.json`
  gespeichert und beim Start wiederhergestellt (Off-Screen-Schutz bei Monitorwechseln,
  DPI-korrekt da WinForms logische Koordinaten nutzt).
- Wrapper neu gebaut (`dotnet publish`); beim Deployment bleiben neben den Signaturen jetzt
  auch `einstellungen.json`/`fenster.json` erhalten.

## v0.8.1 — Fix: Signatur-Kopien & Löschen
- Fix: Nach Zoomen verdoppelten sich die Overlays (Signatur-/Text-"Kopien"). Ursache: Das
  Scharfstellen des Seitenrasters (loadFresh) feuerte img.onload → buildPage baute die Overlays
  NEU, ohne die alten zu entfernen. Jetzt: onload wird beim stillen Bildtausch gelöst; buildPage
  räumt vor dem Neuaufbau auf und entwertet laufende Aufbauten per Generationen-Token (deckt auch
  die Undo-Race zwischen refreshPage und reloadAnnots ab). Server-PDF war nie betroffen
  (nachgewiesen per Repro: set_rect erzeugt keine Duplikate).
- Neu: Rechtsklick auf Signatur/Text öffnet eigenes Kontextmenü (Löschen; Text zusätzlich
  Bearbeiten) — statt des WebView2-Bildmenüs ("Bild speichern"/"Bild kopieren"). Eingabefelder
  behalten ihr natives Menü.
- Neu: Entf-Taste löscht die ausgewählte Signatur/Text (Strg+Z holt beides zurück).

## v0.8 — Freihand-Auswahl, Miniaturen, Rückgängig
- Text per Maus aufziehen und kopieren (Auswahlrechteck, Chip „Kopieren", Strg+C)
- Miniatur-Leiste links (Klick springt, aktuelle Seite markiert, ein-/ausblendbar)
- Rückgängig (Strg+Z / Knopf) für Objekte, Verschieben, Formularfelder, Drehen
- Fix: Formularfelder leeren war unmöglich (PyMuPDF ignoriert „")
- Tests auf Isolation umgestellt (25 Checks, fassen Nutzerdaten nicht mehr an)

## v0.7.x — Inline-Text, Layout-Freiheit
- Texteingabe direkt auf dem PDF (kein Dialogfenster); Schrift/Stil/Größe/Farbe in der Kopfzeiste, wirkt live
- Fix: Verschieben von Text/Signatur sprang zur alten Position zurück (Server + Frontend)
- Theme-Schalter hell/dunkel (bleibt gespeichert)
- Seitenleiste: links/rechts verlegbar, einklappbar über Griff „< >" an der Kante
- Eigenschaftsleiste X/Y/Breite/Höhe für ausgewählte Objekte; Signatur nach Platzierung sofort ausgewählt
- Toolbar responsiv: Beschriftungen→Icons→Marke aus→zweite Reihe

## v0.6.x — Signatur-Verwaltung, Icons, Polish
- Signaturen-Galerie mit Vorschaubildern, Umbenennen und Löschen (Verweise in Dokumenten ziehen mit)
- Fix: erstes Zeichen von Signaturdateinamen wurde abgeschnitten (Off-by-one)
- Fix: Edge-Fehlerseite beim Start (Splash + Health-Poll, eigener Fehlerbildschirm)
- Fix: WebView2-Cache lieferte alte UI (globales no-cache)
- Fix: wörtliche \uXXXX-Escapes im HTML (62 Stellen auf echte Umlaute)
- Programm-Icon in drei Versionen (final: transparent, Deutschland-Schlinge)

## v0.5 — Aussehen und Grundausstattung
- Komplettes UI-Redesign (Fluent-dark), Statusleiste, Icons
- Zoom (jetzt v0.6.4 fluid: stufenlos, ohne Flackern, Scharfstellung im Hintergrund)
- Volltextsuche mit Treffer-Navigation, Seiten-Navigation, Drehen, Seite löschen
- Drucken (inkl. Signaturen, Texte, Formularwerte), Drag&Drop, Strg+S/O, Esc
- Schließen-Schutz bei ungespeicherten Änderungen (Dialog: Speichern/Verwerfen/Abbrechen)
- Lokale EXE-Installtion ersetzt den Webserver-Betrieb

## v0.4 — Annotation-Architektur
- Signaturen und Texte sind echte, bewegliche PDF-Annotationen (kein Einbrennen)
- Signaturen: Stamp-Annotation mit selbstgebauter Bild-Erscheinung (Bild+SMask+Form)
- Texte: FreeText-Annotationen, Editierbarkeit durch Neu-Erzeugen

## v0.3 — Die fünf Kernfunktionen
- Lesezeichenübersicht, Signaturen setzen (Hintergrund-Entfernung wie PDFgear),
  Text kopieren (Zeilen-Klick), Formularfelder, Text einfügen/löschen (Redaction)
- 6 Unterschriften aus PDFgear übernommen

## v0.2 — Erstes echtes Programm
- WebView2-Fenster + gebündelter PyInstaller-Server, Doppelklick-Vorbereitung
- Server, Suche-freie Grundansicht, Lesezeichen, Formularfelder, Speichern/Laden

## v0.1 — Prototyp
- Browser-Variante auf dem Entwicklungsrechner (später zugunsten der lokalen EXE eingestellt)
