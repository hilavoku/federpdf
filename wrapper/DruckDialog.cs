using System.Drawing.Drawing2D;
using System.Drawing.Printing;
using System.Runtime.InteropServices;

namespace FederPDF;

/// <summary>Druckdialog im PDFgear-Stil: GROSSE, ZOOMBARE Seitenvorschau links
/// (Mausrad/Zoomknöpfe; die Seiten werden auf dem ECHTEN Blatt des gewählten
/// Druckers komponiert, exakt wie der Druck sie platziert), Einstellungs-
/// spalte rechts mit Drucker, Papierformat, Seiten pro Blatt (N-up),
/// Ausrichtung, Kopien, Seitenbereich, "Signaturen/Markierungen/Formulare
/// drucken" (auch OHNE druckbar), Duplex und Skalierung. Eine Quelle der
/// Wahrheit ist druckerEinstellungen.DefaultPageSettings (Papier/Ausrichtung):
/// Combos, Treiberdialog und Druckauftrag lesen/schreiben dort. Folgt dem
/// App-Theme (hell/dunkel aus der Web-UI-Palette). Rahmenlos wie das Haupt-
/// fenster. DPI: KEIN WinForms-AutoScale (reskalierte den Dialog bei DPI-
/// Wechsel physisch, 144→96 = 2/3, Mess-Fund 22.10.2026) - Layout wird mit
/// dem Owner-DPI-Faktor gebaut, StartPosition.Manual direkt am Zielort.</summary>
internal sealed class DruckDialog : Form
{
    private readonly int seiten;
    private readonly List<int> auftrag;          // 0-basierte Seiten des Drucks
    private readonly Func<int, int, bool, Image> seiteBild;   // (nr, dpi, annots)
    private readonly string spr;
    private readonly int startSeite;             // 1-basiert, aus der UI
    private readonly float f;                    // DPI-Faktor (dpi/96), s. S()
    private readonly double[][] masse;           // Seitenmasse in pt [b,h] je Seite

    // Theme-Paletten (Farben aus der Web-UI: body / body.light)
    private readonly bool hell;
    private readonly Color bg, spalteFarbe, feld, papier, textFarbe, muted, akzent, akzentText, akzentHover;

    private readonly Panel zpanel;
    private readonly PictureBox vorschau;
    private readonly ComboBox drucker, duplex, skalierung;
    private readonly ComboBox papierFormat, proBlatt, ausrichtung;   // Papierformat / N-up / Hoch-Quer
    private readonly RadioButton alles, aktuelle, bereich;
    private readonly NumericUpDown von, bis, kopien, prozent;
    private readonly Button zurueck, weiter, drucken, abbruch, zoomMinus, zoomPlus, zoomPassend, eigenschaften;
    private readonly CheckBox mitAnnots;
    private readonly Label seitenZahl, vorschauInfo, zoomLabel;
    private readonly Panel prozentZeile;
    // Druckereinstellungen des GEWAEHLTEN Druckers (Namen-only-Anlage, keine
    // Treiberabfragen). Der "Druckereigenschaften"-Knopf oeffnet den Treiber-
    // dialog (DocumentProperties/DEVMODE) und wendet die Auswahl HIER an -
    // Paperformat/Qualitaet/Farbe fliessen so in den Druck (PDFgear-Art).
    private PrinterSettings druckerEinstellungen = new();
    // Guard fuer programmatische Combo-Setzungen (Papierliste fuellen,
    // Treiber-Sync): die Handler sollen beim Befuellen NICHT zurueckfeuern
    private bool synchronisiere;
    private int vorschauPos;                     // Blatt-Index (Seiten pro Blatt)
    private double zoomF = 0;                    // 0 = eingepasst, sonst Faktor
    // Vorschau-Debounce: jeder Wertwechsel (Seitenbereich-Pfeile! Skalierung,
    // Annots) loeste SYNCHRON einen HTTP-Abruf auf dem UI-Thread aus - bei
    // Klickserien staute sich die Warteschlange und der Dialog wirkte ver-
    // zaegert/kaputt (Nutzer-Fund: "es aendert sich weiterhin die Bis-Seite").
    // Jetzt: Zahlen stehen sofort, das Bild kommt 250 ms nach dem letzten
    // Klick.
    private readonly System.Windows.Forms.Timer vorschauVerzoegert;

    private string T(string de, string en) => spr == "en" ? en : de;
    private int S(float v) => (int)Math.Round(v * f);
    private Font Ft(float pt, FontStyle stil = FontStyle.Regular)
        => new("Segoe UI", (float)Math.Round(pt * f, 1), stil);

    public string GewaehlterDrucker => drucker.SelectedItem as string ?? "";
    public int Kopien => (int)kopien.Value;
    public List<int> SeitenListe => auftrag;
    public bool MitAnnots => mitAnnots.Checked;
    /// <summary>Einstellungen des gewaehlten Druckers inkl. evtl. im Treiber-
    /// dialog getroffener Auswahl (Papier/Qualitaet/Farbe) - der Druck läuft
    /// mit DIESEM Objekt.</summary>
    public PrinterSettings DruckerEinstellungen => druckerEinstellungen;
    public Duplex DuplexModus => duplex.SelectedIndex switch
    {
        1 => Duplex.Vertical,      // Kante lang
        2 => Duplex.Horizontal,    // Kante kurz
        _ => Duplex.Simplex,
    };
    /// <summary>skalierung 0 = einpassen; sonst Faktor (1,0 = tatsaechliche
    /// Groesse). Bei mehreren Seiten pro Blatt immer Einpassen - ein fester
    /// Massstab pro Zelle ist sinnleer (die Combo ist dann gesperrt).</summary>
    public double Skalierung => SeitenProBlatt > 1 ? 0.0 : skalierung.SelectedIndex switch
    {
        1 => 1.0,
        2 => (double)prozent.Value / 100.0,
        _ => 0.0,
    };

    /// <summary>Seiten pro Blatt (1/2/4/6/9/16) - N-up-Druck.</summary>
    public int SeitenProBlatt
        => proBlatt.SelectedIndex >= 0
            ? DruckLayout.SeitenProBlattWerte[proBlatt.SelectedIndex]
            : 1;

    /// <param name="dpi">DeviceDpi des Owner-Fensters (Layout-Skalierung).</param>
    /// <param name="hellF">App-Theme (true = helles Design der Web-UI).</param>
    /// <param name="seitenmasse">Seitenmasse in pt je Seite (fuer die Blatt-Komposition).</param>
    public DruckDialog(int seitenAnzahl, int aktuelleSeite, Func<int, int, bool, Image> bildLader,
                       string uiSprache, int dpi, bool hellF, double[][] seitenmasse)
    {
        seiten = seitenAnzahl;
        seiteBild = bildLader;
        spr = uiSprache;
        startSeite = Math.Max(1, Math.Min(aktuelleSeite, seiten));
        auftrag = new List<int>();
        f = Math.Max(1, dpi) / 96f;
        masse = seitenmasse;
        hell = hellF;

        if (hell)
        {
            bg = Color.FromArgb(238, 241, 245);        // --bg #eef1f5
            spalteFarbe = Color.FromArgb(230, 234, 240);
            feld = Color.White;                        // --chrome
            papier = Color.FromArgb(221, 227, 234);
            textFarbe = Color.FromArgb(26, 31, 39);    // --text #1a1f27
            muted = Color.FromArgb(98, 108, 122);      // --muted
            akzent = Color.FromArgb(11, 110, 201);     // --accent #0b6ec9
            akzentText = Color.White;
            akzentHover = Color.FromArgb(10, 99, 181);
        }
        else
        {
            bg = Color.FromArgb(23, 25, 29);           // App-Hintergrund
            spalteFarbe = Color.FromArgb(28, 31, 36);
            feld = Color.FromArgb(44, 49, 58);         // #2c313a
            papier = Color.FromArgb(33, 37, 43);
            textFarbe = Color.FromArgb(230, 233, 238); // #e6e9ee
            muted = Color.FromArgb(151, 160, 175);     // #97a0af
            akzent = Color.FromArgb(76, 194, 255);     // #4cc2ff
            akzentText = Color.FromArgb(18, 22, 28);
            akzentHover = Color.FromArgb(120, 208, 255);
        }

        Text = T("Drucken", "Print");
        FormBorderStyle = FormBorderStyle.None;
        MaximizeBox = false; MinimizeBox = false;
        ShowInTaskbar = false;
        BackColor = bg;
        ForeColor = textFarbe;
        Font = Ft(9.5f);
        ClientSize = new Size(S(1080), S(940));

        TitelzeileBauen();
        (zpanel, vorschau, zurueck, weiter, seitenZahl, vorschauInfo,
         zoomMinus, zoomPlus, zoomPassend, zoomLabel) = VorschauBauen();
        (drucker, eigenschaften, papierFormat, proBlatt, ausrichtung, duplex, skalierung,
         alles, aktuelle, bereich, von, bis, kopien, prozent,
         prozentZeile, mitAnnots, drucken, abbruch) = SpalteBauen();

        drucken.Click += (_, _) => { DialogResult = DialogResult.OK; Close(); };
        abbruch.Click += (_, _) => { DialogResult = DialogResult.Cancel; Close(); };
        AcceptButton = drucken;
        CancelButton = abbruch;
        zurueck.Click += (_, _) => Blaettern(-1);
        weiter.Click += (_, _) => Blaettern(1);
        vorschau.MouseClick += (_, e) => { if (e.Button == MouseButtons.Left) vorschau.Select(); };
        // Mausrad ueber der Vorschau = ZOOM (Nutzer-Wunsch "nicht zoombar")
        zpanel.MouseWheel += VorschauRad;
        vorschau.MouseWheel += VorschauRad;
        vorschau.DoubleClick += (_, _) => { zoomF = 0; ZoomAnwenden(); };
        zoomMinus.Click += (_, _) => ZoomSchritt(-0.15);
        zoomPlus.Click += (_, _) => ZoomSchritt(0.15);
        zoomPassend.Click += (_, _) => { zoomF = 0; ZoomAnwenden(); };
        alles.CheckedChanged += (_, _) => AuftragNeu();
        aktuelle.CheckedChanged += (_, _) => AuftragNeu();
        bereich.CheckedChanged += (_, _) => AuftragNeu();
        von.ValueChanged += (_, _) => { if (von.Value > bis.Value) bis.Value = von.Value; AuftragNeu(); };
        bis.ValueChanged += (_, _) => { if (bis.Value < von.Value) von.Value = bis.Value; AuftragNeu(); };
        mitAnnots.CheckedChanged += (_, _) => VorschauVerzoegertStarten();   // Vorschau = echter Druckinhalt
        skalierung.SelectedIndexChanged += (_, _) =>
        {
            prozentZeile.Visible = skalierung.SelectedIndex == 2;
            VorschauVerzoegertStarten();   // Skalierungswechsel sofort sichtbar (Nutzer-Wunsch)
        };
        prozent.ValueChanged += (_, _) => { if (skalierung.SelectedIndex == 2) VorschauVerzoegertStarten(); };

        // Fokus-Routing: Spinner-Klicks fokussieren das NumericUpDown NICHT
        // von selbst - der Caret blieb im vorherigen Feld stehen und Pfeil-
        // tasten veraenderten weiter DAS (Nutzer-Fund). Nach Spinner-Klick
        // das eigene Feld fokussieren; beim Aktivieren des Seitenbereichs
        // landet der Caret im Von-Feld.
        void SpinnerFokussieren(NumericUpDown num)
        {
            foreach (Control c in num.Controls)
                if (c is not TextBox) c.MouseUp += (_, _) => num.Select();
        }
        SpinnerFokussieren(von);
        SpinnerFokussieren(bis);
        SpinnerFokussieren(kopien);
        SpinnerFokussieren(prozent);
        bereich.CheckedChanged += (_, _) => { if (bereich.Checked) von.Select(); };

        // Wer die Von/Bis-Felder anfasst, meint den Seitenbereich: Option
        // automatisch aktivieren (Nutzer-Fund: Zahlen aenderten sich, aber
        // der Auftrag blieb auf "Alle Seiten" - die Vorschau reagierte nicht)
        von.Enter += (_, _) => { if (!bereich.Checked) bereich.Checked = true; };
        bis.Enter += (_, _) => { if (!bereich.Checked) bereich.Checked = true; };

        vorschauVerzoegert = new System.Windows.Forms.Timer { Interval = 250 };
        vorschauVerzoegert.Tick += (_, _) => { vorschauVerzoegert.Stop(); VorschauLaden(); };

        alles.Checked = true;
        AuftragNeu();
        Load += (_, _) => { EckenRunden(); VorschauLaden(); };
    }

    /// <summary>Auf dem Owner zentrieren und per StartPosition.Manual direkt
    /// dort erstellen — der Dialog entsteht im DPI-Kontext des Owners und
    /// erfährt keinen DPI-Wechsel nach der Erstellung.</summary>
    public void ZentrierenAuf(Form owner)
    {
        StartPosition = FormStartPosition.Manual;
        Location = new Point(owner.Left + (owner.Width - Width) / 2,
                             Math.Max(owner.Top, owner.Top + (owner.Height - Height) / 2));
    }

    private void VorschauRad(object? s, MouseEventArgs e)
    {
        WheelVerarbeiten((Control.ModifierKeys & Keys.Control) == Keys.Control, e.Delta);
        if (e is HandledMouseEventArgs h) h.Handled = true;
    }

    /// <summary>Mausrad-Umleitung (extrahiert fuer den kopflosen Test):
    /// ohne Strg = blaettern (im eingepassten Zustand) bzw. Inhalts-Scrollen
    /// (gezoomt); Strg = Zoom (Konvention; Nutzer-Fund: Zoom allein aufs Rad
    /// war "falsch").</summary>
    internal void WheelVerarbeiten(bool strg, int delta)
    {
        if (strg)
        {
            ZoomSchritt(delta > 0 ? 0.15 : -0.15);
        }
        else if (zoomF > 0)
        {
            var pos = zpanel.AutoScrollPosition;
            zpanel.AutoScrollPosition = new Point(-pos.X, -pos.Y + (delta > 0 ? -80 : 80));
        }
        else
        {
            Blaettern(delta > 0 ? -1 : 1);
        }
    }

    // ---------------------------------------------------------------- kopfloser Test
    /// <summary>Drucker per Namen waehlen (feuert den normalen Wechsel-Pfad:
    /// frische PrinterSettings, Papierliste, Ausrichtung, Vorschau) - intern
    /// fuer den kopflosen Test.</summary>
    internal void DruckerWaehlen(string name)
    {
        drucker.SelectedItem = name;
    }

    internal Image? VorschauBildFuerTest => vorschau.Image;

    internal int VorschauPosFuerTest => vorschauPos;
    internal bool SkalierungAktivFuerTest => skalierung.Enabled;
    internal int AusrichtungFuerTest => ausrichtung.SelectedIndex;
    internal int PapierFormateFuerTest => papierFormat.Items.Count;
    internal string PapierAktuellFuerTest => (papierFormat.SelectedItem as PaperSize)?.PaperName ?? "";

    /// <summary>Ausrichtung ueber die ECHTE Combo setzen (feuert den normalen
    /// Pfad: DefaultPageSettings + Vorschau) - intern fuer den kopflosen Test.</summary>
    internal void AusrichtungWaehlen(bool quer)
    {
        ausrichtung.SelectedIndex = quer ? 1 : 0;
    }

    /// <summary>"Seiten pro Blatt" ueber die ECHTE Combo setzen - intern.</summary>
    internal void SeitenProBlattWaehlen(int n)
    {
        int ix = Array.IndexOf(DruckLayout.SeitenProBlattWerte, n);
        if (ix >= 0) proBlatt.SelectedIndex = ix;
    }

    /// <summary>Papierformat ueber die ECHTE Combo setzen - intern.</summary>
    internal void PapierWaehlen(string papierName)
    {
        int ix = papierFormat.Items.Cast<PaperSize>().ToList()
            .FindIndex(f => f.PaperName == papierName);
        if (ix >= 0) papierFormat.SelectedIndex = ix;
    }

    private void ZoomSchritt(double delta)
    {
        zoomF = Math.Clamp((zoomF <= 0 ? 1.0 : zoomF) + delta, 0.3, 4.0);
        ZoomAnwenden();
    }

    // ---------------------------------------------------------------- Titelzeile
    private void TitelzeileBauen()
    {
        var leiste = new Panel { Dock = DockStyle.Top, Height = S(48), BackColor = bg };
        var titelText = new Label
        {
            Text = T("Drucken", "Print"),
            Font = Ft(12.5f, FontStyle.Bold),
            ForeColor = textFarbe,
            AutoSize = true,
            Location = new Point(S(20), S(11)),
        };
        var zuBtn = new Button
        {
            Text = "\u2715",
            Font = Ft(10f),
            Size = new Size(S(34), S(34)),
            Location = new Point(ClientSize.Width - S(44), S(7)),
            FlatStyle = FlatStyle.Flat,
            BackColor = bg,
            ForeColor = muted,
            Anchor = AnchorStyles.Top | AnchorStyles.Right,
        };
        zuBtn.FlatAppearance.BorderSize = 0;
        zuBtn.FlatAppearance.MouseOverBackColor = Color.FromArgb(221, 0, 0);
        zuBtn.FlatAppearance.MouseDownBackColor = Color.FromArgb(160, 0, 0);
        zuBtn.Click += (_, _) => { DialogResult = DialogResult.Cancel; Close(); };
        leiste.Controls.Add(titelText);
        leiste.Controls.Add(zuBtn);
        leiste.MouseDown += LeisteZiehen;
        titelText.MouseDown += LeisteZiehen;
        Controls.Add(leiste);
    }

    private void LeisteZiehen(object? s, MouseEventArgs e)
    {
        if (e.Button == MouseButtons.Left)
        {
            ReleaseCapture();
            _ = SendMessage(Handle, WM_NCLBUTTONDOWN, HTCAPTION, 0);
        }
    }

    // ---------------------------------------------------------------- Vorschau
    private (Panel, PictureBox, Button, Button, Label, Label, Button, Button, Button, Label) VorschauBauen()
    {
        var zone = new Panel
        {
            Location = new Point(0, S(48)),
            Size = new Size(S(748), ClientSize.Height - S(48)),
            BackColor = papier,
        };
        // Zoombare Flaeche: AutoScroll-Panel um das Bild
        var zp = new Panel
        {
            AutoScroll = true,
            Location = new Point(S(44), S(70)),
            Size = new Size(S(660), S(620)),
            BackColor = papier,
        };
        var bild = new PictureBox
        {
            SizeMode = PictureBoxSizeMode.Zoom,
            // Blatt + Schatten kommen im KOMPOSIT (transparenter Grund) - der
            // Rahmen hier waere ein zweiter Kasten ums Blatt (Nutzer-Fund:
            // "muesste eine DIN-A4-Seite sehen" wie bei PDFgear)
            BackColor = papier,
            BorderStyle = BorderStyle.None,
            Dock = DockStyle.Fill,
        };
        zp.Controls.Add(bild);
        zp.Resize += (_, _) => ZoomAnwenden();
        zone.Controls.Add(zp);

        // Fusszeile: Koordinaten ZONEN-relativ! (Frueher Dialog-Koordinaten in
        // der Zone als Parent - alles sass S(48) zu tief, Seitenzahl/
        // "Angepasst"/Info waren unten abgeschnitten, Nutzer-Fund 150 %--Notebook)
        Button Nav(string t, int x) => new()
        {
            Text = t,
            Font = Ft(15f),
            Size = new Size(S(44), S(34)),
            Location = new Point(S(x), zone.Height - S(78)),
            FlatStyle = FlatStyle.Flat,
            BackColor = papier,
            ForeColor = textFarbe,
        };
        var zr = Nav("\u2039", 290);
        var zv = Nav("\u203A", 410);
        zr.FlatAppearance.BorderSize = 0; zv.FlatAppearance.BorderSize = 0;
        zr.FlatAppearance.MouseOverBackColor = feld; zv.FlatAppearance.MouseOverBackColor = feld;

        var zahl = new Label
        {
            Text = "1 / 1",
            Font = Ft(10.5f),
            ForeColor = textFarbe,
            TextAlign = ContentAlignment.MiddleCenter,
            Size = new Size(S(110), S(34)),
            Location = new Point(S(317), zone.Height - S(74)),
        };

        // Zoom-Gruppe rechts in der Fusszeile der Vorschau
        Button Zoomk(string t, int x) => new()
        {
            Text = t,
            Font = Ft(11f),
            Size = new Size(S(36), S(30)),
            Location = new Point(S(x), zone.Height - S(76)),
            FlatStyle = FlatStyle.Flat,
            BackColor = papier,
            ForeColor = textFarbe,
        };
        var zm = Zoomk("\u2212", 500);   // −
        var zp2 = Zoomk("+", 628);
        var zf = Zoomk("\u2922", 670);   // Anpassen-Symbol
        zm.FlatAppearance.BorderSize = 0; zp2.FlatAppearance.BorderSize = 0; zf.FlatAppearance.BorderSize = 0;
        zm.FlatAppearance.MouseOverBackColor = feld; zp2.FlatAppearance.MouseOverBackColor = feld; zf.FlatAppearance.MouseOverBackColor = feld;
        var zl = new Label
        {
            Text = T("Angepasst", "Fit"),
            Font = Ft(9.5f),
            ForeColor = muted,
            TextAlign = ContentAlignment.MiddleCenter,
            Size = new Size(S(88), S(30)),
            Location = new Point(S(538), zone.Height - S(73)),
        };

        var info = new Label
        {
            Text = "",
            Font = Ft(8.25f),
            ForeColor = muted,
            TextAlign = ContentAlignment.MiddleCenter,
            Size = new Size(S(500), S(20)),
            Location = new Point(S(124), zone.Height - S(40)),
        };
        zone.Controls.Add(zr); zone.Controls.Add(zv); zone.Controls.Add(zahl);
        zone.Controls.Add(zm); zone.Controls.Add(zp2); zone.Controls.Add(zf); zone.Controls.Add(zl);
        zone.Controls.Add(info);
        Controls.Add(zone);
        return (zp, bild, zr, zv, zahl, info, zm, zp2, zf, zl);
    }

    // ---------------------------------------------------------------- Spalte rechts
    private (ComboBox, Button, ComboBox, ComboBox, ComboBox, ComboBox, ComboBox,
             RadioButton, RadioButton, RadioButton,
             NumericUpDown, NumericUpDown, NumericUpDown, NumericUpDown,
             Panel, CheckBox, Button, Button) SpalteBauen()
    {
        int rand = S(26), fw = S(332) - rand * 2;
        var spalte = new Panel
        {
            Location = new Point(S(748), S(48)),
            Size = new Size(S(332), ClientSize.Height - S(48)),
            BackColor = spalteFarbe,
        };

        ComboBox Kombi() => new()
        {
            Size = new Size(fw, S(34)),
            DropDownStyle = ComboBoxStyle.DropDownList,
            FlatStyle = FlatStyle.Flat,
            BackColor = feld,
            ForeColor = textFarbe,
            Font = Ft(10f),
        };

        int y = S(24);

        spalte.Controls.Add(Caption(T("Drucker", "Printer"), ref y, rand));
        var cb = Kombi(); cb.Location = new Point(rand, y);
        try
        {
            // NUR Namen - KEINE Statusabfragen: die blockieren an schlafenden
            // Netzwerkdruckern die Dialog-Anzeige
            foreach (string p in PrinterSettings.InstalledPrinters) cb.Items.Add(p);
            string def = "";
            try { def = new PrinterSettings().PrinterName; } catch { }
            int i = def.Length > 0 ? cb.Items.IndexOf(def) : -1;
            cb.SelectedIndex = i >= 0 ? i : (cb.Items.Count > 0 ? 0 : -1);
        }
        catch { }
        spalte.Controls.Add(cb);
        // Einstellungen folgen der Auswahl (nur Name - Treiberabfragen erst
        // beim Eigenschaften-Knopf bzw. im Druck-Background-Task). Papier-
        // formate/Hoch-Quer des neuen Druckers uebernehmen, Vorschau aktualisieren.
        cb.SelectedIndexChanged += (_, _) =>
        {
            if (cb.SelectedItem is not string name) return;
            druckerEinstellungen = new PrinterSettings { PrinterName = name };
            PapierListeFuellen(papierFormat);
            AusrichtungSynchronisieren();
            if (IsHandleCreated) VorschauVerzoegertStarten();
        };
        if (cb.SelectedItem is string startName)
            druckerEinstellungen = new PrinterSettings { PrinterName = startName };
        y += S(34 + 8);

        // Treiber-Eigenschaften (PDFgear-Art): oeffnet den Dialog des
        // Druckertreibers (Papier, Qualitaet, Farbe ...) und wendet die
        // Auswahl auf den Druck an
        var eg = new Button
        {
            Text = T("\u2699  Druckereigenschaften", "\u2699  Printer properties"),
            Font = Ft(9.5f),
            Size = new Size(fw, S(30)),
            Location = new Point(rand, y),
            FlatStyle = FlatStyle.Flat,
            BackColor = feld,
            ForeColor = textFarbe,
            Cursor = Cursors.Hand,
        };
        eg.FlatAppearance.BorderSize = 0;
        eg.FlatAppearance.MouseOverBackColor = hell ? SystemColors.Control : Color.FromArgb(58, 64, 74);
        eg.Click += (_, _) => TreiberEigenschaftenZeigen();
        spalte.Controls.Add(eg);
        y += S(30 + 16);

        // Papierformat: Formate des GEWAEHLTEN Druckers (Nur-Namen-Daten,
        // KEINE Statusabfragen - Pitfall schlafende Netzwerkdrucker). Eine
        // Quelle der Wahrheit: druckerEinstellungen.DefaultPageSettings -
        // die Combo spiegelt sie, der Treiberdialog schreibt hinein
        // (SetHdevmode), der Druck liest sie.
        spalte.Controls.Add(Caption(T("Papierformat", "Paper size"), ref y, rand));
        var pf = Kombi(); pf.Location = new Point(rand, y);
        spalte.Controls.Add(pf);
        y += S(34 + 8);
        pf.SelectedIndexChanged += (_, _) =>
        {
            if (synchronisiere || pf.SelectedItem is not PaperSize gewaehlt) return;
            try { druckerEinstellungen.DefaultPageSettings.PaperSize = gewaehlt; } catch { }
            VorschauVerzoegertStarten();
        };
        PapierListeFuellen(pf);

        // Seiten pro Blatt (N-up) + Ausrichtung teilen sich eine Zeile
        int halb = (fw - S(12)) / 2;
        var capL = new Label
        {
            Text = T("Seiten pro Blatt", "Pages per sheet").ToUpper(),
            Font = Ft(8.25f, FontStyle.Bold),
            ForeColor = muted,
            AutoSize = true,
            Location = new Point(rand, y),
        };
        var capR = new Label
        {
            Text = T("Ausrichtung", "Orientation").ToUpper(),
            Font = Ft(8.25f, FontStyle.Bold),
            ForeColor = muted,
            AutoSize = true,
            Location = new Point(rand + halb + S(12), y),
        };
        y += S(24);
        var pb = Kombi(); pb.Size = new Size(halb, S(34)); pb.Location = new Point(rand, y);
        foreach (int n in DruckLayout.SeitenProBlattWerte)
            pb.Items.Add(n == 1 ? T("1 Seite", "1 page") : string.Format(T("{0} Seiten", "{0} pages"), n));
        pb.SelectedIndex = 0;
        pb.SelectedIndexChanged += (_, _) =>
        {
            if (synchronisiere) return;
            skalierung.Enabled = SeitenProBlatt == 1;   // Anzeige=Verhalten
            VorschauVerzoegertStarten();
        };
        var au = Kombi(); au.Size = new Size(fw - halb - S(12), S(34)); au.Location = new Point(rand + halb + S(12), y);
        au.Items.AddRange(new object[] { T("Hochformat", "Portrait"), T("Querformat", "Landscape") });
        au.SelectedIndex = LiesQuer() ? 1 : 0;
        au.SelectedIndexChanged += (_, _) =>
        {
            if (synchronisiere) return;
            try { druckerEinstellungen.DefaultPageSettings.Landscape = au.SelectedIndex == 1; } catch { }
            VorschauVerzoegertStarten();
        };
        spalte.Controls.Add(capL); spalte.Controls.Add(capR); spalte.Controls.Add(pb); spalte.Controls.Add(au);
        y += S(34 + 16);

        spalte.Controls.Add(Caption(T("Kopien", "Copies"), ref y, rand));
        var ko = new NumericUpDown
        {
            Location = new Point(rand, y),
            Size = new Size(S(120), S(32)),
            Minimum = 1, Maximum = 99, Value = 1,
            BackColor = feld, ForeColor = textFarbe, BorderStyle = BorderStyle.None,
            Font = Ft(10.5f),
            TextAlign = HorizontalAlignment.Center,
        };
        spalte.Controls.Add(ko);
        y += S(32 + 20);

        spalte.Controls.Add(Caption(T("Seiten", "Pages"), ref y, rand));
        y += S(6);
        var ra = Radio(string.Format(T("Alle Seiten ({0})", "All pages ({0})"), seiten), ref y, rand);
        var rk = Radio(string.Format(T("Aktuelle Seite ({0})", "Current page ({0})"), startSeite), ref y, rand);
        var rb = Radio(T("Seitenbereich", "Page range"), ref y, rand);
        spalte.Controls.Add(ra); spalte.Controls.Add(rk); spalte.Controls.Add(rb);
        y += S(6);

        var vonL = new Label { Text = T("von", "from"), Font = Ft(9f), ForeColor = muted, AutoSize = true, Location = new Point(rand + S(28), y + S(6)) };
        var vn = new NumericUpDown
        {
            Location = new Point(rand + S(66), y),
            Size = new Size(S(88), S(30)),
            Minimum = 1, Maximum = seiten, Value = 1,
            BackColor = feld, ForeColor = textFarbe, BorderStyle = BorderStyle.None,
            Font = Ft(10f), TextAlign = HorizontalAlignment.Center,
        };
        var bisL = new Label { Text = T("bis", "to"), Font = Ft(9f), ForeColor = muted, AutoSize = true, Location = new Point(rand + S(164), y + S(6)) };
        var bs = new NumericUpDown
        {
            Location = new Point(rand + S(196), y),
            Size = new Size(S(88), S(30)),
            Minimum = 1, Maximum = seiten, Value = seiten,
            BackColor = feld, ForeColor = textFarbe, BorderStyle = BorderStyle.None,
            Font = Ft(10f), TextAlign = HorizontalAlignment.Center,
        };
        spalte.Controls.Add(vonL); spalte.Controls.Add(vn); spalte.Controls.Add(bisL); spalte.Controls.Add(bs);
        y += S(30 + 14);

        // Was gedruckt wird (Nutzer-Wunsch: auch OHNE Markierungen druckbar).
        // Die Vorschau schaltet live mit, sie zeigt stets den echten Druckinhalt.
        var chk = new CheckBox
        {
            Text = T("Signaturen, Markierungen und\nFormulare drucken", "Print signatures, markup\nand form fields"),
            Font = Ft(9.5f),
            ForeColor = textFarbe,
            Checked = true,
            AutoSize = true,
            Location = new Point(rand, y),
        };
        spalte.Controls.Add(chk);
        y += S(48 + 14);

        spalte.Controls.Add(Caption(T("Duplex", "Duplex"), ref y, rand));
        var du = Kombi(); du.Location = new Point(rand, y);
        du.Items.AddRange(new object[]
        {
            T("Einseitig", "One-sided"),
            T("Beidseitig – Kante lang", "Two-sided – long edge"),
            T("Beidseitig – Kante kurz", "Two-sided – short edge"),
        });
        du.SelectedIndex = 0;
        spalte.Controls.Add(du);
        y += S(34 + 20);

        spalte.Controls.Add(Caption(T("Skalierung", "Scaling"), ref y, rand));
        var sk = Kombi(); sk.Location = new Point(rand, y);
        sk.Items.AddRange(new object[]
        {
            T("An Seitenrand anpassen", "Fit to page"),
            T("Tatsächliche Größe", "Actual size"),
            T("Benutzerdefiniert", "Custom"),
        });
        sk.SelectedIndex = 0;
        spalte.Controls.Add(sk);
        y += S(34 + 8);

        // Prozentzeile (Platz reserviert, sichtbar nur bei "Benutzerdefiniert")
        var pz = new Panel { Location = new Point(rand, y), Size = new Size(fw, S(30)), BackColor = spalteFarbe, Visible = false };
        var pzFeld = new NumericUpDown
        {
            Location = new Point(0, 0),
            Size = new Size(S(88), S(30)),
            Minimum = 25, Maximum = 400, Value = 100,
            BackColor = feld, ForeColor = textFarbe, BorderStyle = BorderStyle.None,
            Font = Ft(10f), TextAlign = HorizontalAlignment.Center,
        };
        var pzL = new Label { Text = "%", Font = Ft(10f), ForeColor = muted, AutoSize = true, Location = new Point(S(96), S(5)) };
        pz.Controls.Add(pzFeld); pz.Controls.Add(pzL);
        spalte.Controls.Add(pz);

        var ok = new Button
        {
            Text = T("Drucken", "Print"),
            Font = Ft(10.5f, FontStyle.Bold),
            Size = new Size(fw, S(46)),
            Location = new Point(rand, spalte.Height - S(26 + 46 + 10 + 36)),
            FlatStyle = FlatStyle.Flat,
            BackColor = akzent,
            ForeColor = akzentText,
            Anchor = AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right,
        };
        ok.FlatAppearance.BorderSize = 0;
        ok.FlatAppearance.MouseOverBackColor = akzentHover;
        var ab = new Button
        {
            Text = T("Abbrechen", "Cancel"),
            Font = Ft(10f),
            Size = new Size(fw, S(36)),
            Location = new Point(rand, spalte.Height - S(26 + 36)),
            FlatStyle = FlatStyle.Flat,
            BackColor = feld,
            ForeColor = textFarbe,
            Anchor = AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right,
        };
        ab.FlatAppearance.BorderSize = 0;
        ab.FlatAppearance.MouseOverBackColor = hell ? SystemColors.Control : Color.FromArgb(58, 64, 74);
        spalte.Controls.Add(ok); spalte.Controls.Add(ab);

        var trenn = hell ? Color.FromArgb(210, 216, 224) : Color.FromArgb(38, 42, 48);
        spalte.Paint += (_, e) =>
        {
            using var stift = new Pen(trenn);
            e.Graphics.DrawLine(stift, 0, 0, 0, spalte.Height);
        };

        Controls.Add(spalte);
        return (cb, eg, pf, pb, au, du, sk, ra, rk, rb, vn, bs, ko, pzFeld, pz, chk, ok, ab);
    }

    private Label Caption(string text, ref int y, int rand)
    {
        var l = new Label
        {
            Text = text.ToUpper(),
            Font = Ft(8.25f, FontStyle.Bold),
            ForeColor = muted,
            AutoSize = true,
            Location = new Point(rand, y),
        };
        y += S(24);
        return l;
    }

    private RadioButton Radio(string text, ref int y, int rand)
    {
        var r = new RadioButton
        {
            Text = text,
            Font = Ft(10f),
            ForeColor = textFarbe,
            AutoSize = true,
            Location = new Point(rand, y),
        };
        y += S(30);
        return r;
    }

    // ---------------------------------------------------------------- Logik
    private void AuftragNeu()
    {
        auftrag.Clear();
        if (aktuelle.Checked) auftrag.Add(startSeite - 1);
        else if (bereich.Checked)
        {
            for (int p = (int)von.Value; p <= (int)bis.Value; p++) auftrag.Add(p - 1);
        }
        else
        {
            for (int p = 1; p <= seiten; p++) auftrag.Add(p - 1);
        }
        vorschauPos = 0;
        if (IsHandleCreated) VorschauVerzoegertStarten();
    }

    /// <summary>Anzahl Vorschau-/Druckblaetter im aktuellen Auftrag
    /// (Auftragsseiten aufgeteilt zu "Seiten pro Blatt").</summary>
    private int BlattAnzahl()
        => auftrag.Count == 0 ? 0 : (auftrag.Count + SeitenProBlatt - 1) / SeitenProBlatt;

    private void Blaettern(int delta)
    {
        int blaetter = BlattAnzahl();
        if (blaetter == 0) return;
        vorschauPos = Math.Max(0, Math.Min(blaetter - 1, vorschauPos + delta));
        VorschauVerzoegertStarten();
    }

    /// <summary>Seite(n) auf das ECHTE Blatt des gewaehlten Druckers kompo-
    /// nieren, GENAU wie der Druck sie platziert: Papierformat/Ausrichtung
    /// aus druckerEinstellungen (DruckLayout.BlattMasse), Einpassen in die
    /// druckbare Flaeche (gedreht, WENN das mehr Flaeche nutzt - wie
    /// SeiteEinpassen), N-up als Gitter mit Zellabstand, fester Faktor =
    /// 1:1-Massstab zentriert, Ueberhaenge clippt das Blatt wie der Treiber
    /// das Papier. Das Blatt steht mit Schatten und Rand auf TRANSPARENTEM
    /// Grund - die graue Zone scheint durch, man sieht das Blatt wie bei
    /// PDFgear (Nutzer-Wunsch).</summary>
    private Image BlattAnsicht(List<(Image bild, double bPt, double hPt)> seiten)
    {
        var (blattB, blattH, druckbar) = DruckLayout.BlattMasse(druckerEinstellungen);
        int bh = 1600;
        int bb = (int)Math.Round(blattB / blattH * bh);
        int sch = (int)Math.Round(bh * 0.014);         // Schattenwurf ~ Reserve
        var img = new Bitmap(bb + 2 * sch, bh + 2 * sch, System.Drawing.Imaging.PixelFormat.Format32bppArgb);
        using var g = Graphics.FromImage(img);
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.SmoothingMode = System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
        g.Clear(Color.Transparent);
        float px = (float)(bh / blattH);   // pt -> px
        g.ScaleTransform(px, px);          // ab hier in pt zeichnen
        float schPt = sch / px;

        var blatt = new RectangleF(schPt, schPt, (float)blattB, (float)blattH);
        // Schatten: zwei weich gestaffelte Lagen unter dem Blatt
        using (var s1 = new SolidBrush(Color.FromArgb(26, 0, 0, 0)))
            g.FillRectangle(s1, blatt.X + schPt, blatt.Y + schPt, (float)blattB, (float)blattH);
        using (var s2 = new SolidBrush(Color.FromArgb(48, 0, 0, 0)))
            g.FillRectangle(s2, blatt.X + schPt / 2, blatt.Y + schPt / 2, (float)blattB, (float)blattH);
        // Blatt
        g.FillRectangle(Brushes.White, blatt);

        double skal = Skalierung;   // bei N-up erzwingt die Combo Einpassen
        var (spalten, zeilen) = seiten.Count == 1
            ? (1, 1)
            : DruckLayout.Gitter(seiten.Count, druckbar.Width, druckbar.Height,
                                 seiten[0].bPt, seiten[0].hPt);
        float kontur = (float)(blattH * 0.00375);   // 6 px auf 1600 px Hoehe wie bisher
        for (int i = 0; i < seiten.Count; i++)
        {
            var (bild, bPt, hPt) = seiten[i];
            var zelle = seiten.Count == 1 ? druckbar : DruckLayout.Zelle(druckbar, spalten, zeilen, i);
            var (ziel, drehen) = DruckLayout.SeiteInZelle(bPt, hPt, zelle, skal);
            if (drehen) bild.RotateFlip(RotateFlipType.Rotate90FlipNone);   // wie im Druck
            g.DrawImage(bild, ziel);
            // Seitenkontur: weiße Seiten waeren auf weißem Blatt unsichtbar -
            // die dezente Umrandung macht Zellen/Skalierung immer sichtbar.
            // Nach INNEN versetzt: bei 100 % deckt die Seite das Blatt exakt.
            using (var stift = new Pen(Color.FromArgb(190, 197, 208), kontur))
                g.DrawRectangle(stift, ziel.X + kontur / 2, ziel.Y + kontur / 2,
                                ziel.Width - kontur, ziel.Height - kontur);
        }
        // Blattrand
        using (var rand = new Pen(hell ? Color.FromArgb(205, 210, 219) : Color.FromArgb(82, 88, 98), kontur))
            g.DrawRectangle(rand, blatt.X, blatt.Y, (float)blattB, (float)blattH);
        return img;
    }

    /// <summary>Papierformat-Combo aus den Formaten des GEWAEHLTEN Druckers
    /// fuellen und dessen Standard-Format waehlen (Guard verhindert den
    /// Vorschau-Neustart beim Befuellen). Duplikate ausfiltern; ein
    /// Default-Format, das in der Treiberliste fehlt, wandert vorne rein.</summary>
    private void PapierListeFuellen(ComboBox pf)
    {
        synchronisiere = true;
        try
        {
            pf.DisplayMember = nameof(PaperSize.PaperName);
            pf.Items.Clear();
            var formate = new List<PaperSize>();
            try
            {
                foreach (PaperSize p in druckerEinstellungen.PaperSizes)
                    if (!string.IsNullOrEmpty(p.PaperName) && !formate.Any(f => f.PaperName == p.PaperName))
                        formate.Add(p);
            }
            catch { }
            PaperSize? aktuell = null;
            try { aktuell = druckerEinstellungen.DefaultPageSettings.PaperSize; } catch { }
            if (aktuell != null && !string.IsNullOrEmpty(aktuell.PaperName)
                && !formate.Any(f => f.PaperName == aktuell.PaperName))
                formate.Insert(0, aktuell);
            foreach (var f in formate) pf.Items.Add(f);
            int ix = aktuell != null ? formate.FindIndex(f => f.PaperName == aktuell.PaperName) : -1;
            pf.SelectedIndex = ix >= 0 ? ix : (formate.Count > 0 ? 0 : -1);
        }
        finally { synchronisiere = false; }
    }

    /// <summary>Papier-Combo auf das aktuelle DefaultPageSettings-Papier
    /// stellen (nach Treiberdialog/Druckerwechsel). Ein dort gesetztes Format,
    /// das in der Liste fehlt, fuellt die Liste neu - intern fuer den
    /// kopflosen Test.</summary>
    internal void PapierSynchronisieren()
    {
        PaperSize? aktuell = null;
        try { aktuell = druckerEinstellungen.DefaultPageSettings.PaperSize; } catch { }
        if (aktuell == null) return;
        synchronisiere = true;
        try
        {
            int ix = papierFormat.Items.Cast<PaperSize>().ToList()
                .FindIndex(f => f.PaperName == aktuell.PaperName);
            if (ix >= 0) papierFormat.SelectedIndex = ix;
            else PapierListeFuellen(papierFormat);
        }
        finally { synchronisiere = false; }
    }

    /// <summary>Ausrichtungs-Combo aus druckerEinstellungen lesen (nach
    /// Treiberdialog/Druckerwechsel) - intern fuer den kopflosen Test.</summary>
    internal void AusrichtungSynchronisieren()
    {
        synchronisiere = true;
        try { ausrichtung.SelectedIndex = LiesQuer() ? 1 : 0; }
        finally { synchronisiere = false; }
    }

    private bool LiesQuer()
    {
        try { return druckerEinstellungen.DefaultPageSettings.Landscape; }
        catch { return false; }
    }

    /// <summary>Labels sofort aktualisieren und das Laden des Vorschaubilds
    /// 250 ms verz?gern - Klickserien (Seitenbereich-Pfeile) triggern so nur
    /// EINEN Abruf nach Pause statt jeden Klick einzeln zu blockieren.</summary>
    private void VorschauVerzoegertStarten()
    {
        NavAktualisieren();
        vorschauVerzoegert.Stop();
        vorschauVerzoegert.Start();
    }

    private void NavAktualisieren()
    {
        int blaetter = BlattAnzahl();
        if (vorschauPos >= blaetter) vorschauPos = Math.Max(0, blaetter - 1);
        zurueck.Enabled = vorschauPos > 0;
        weiter.Enabled = vorschauPos < blaetter - 1;
        if (auftrag.Count == 0)
        {
            vorschau.Image = null;
            seitenZahl.Text = "-";
            vorschauInfo.Text = T("Keine Seiten gewählt.", "No pages selected.");
            return;
        }
        if (SeitenProBlatt == 1)
        {
            int nr = auftrag[vorschauPos];
            seitenZahl.Text = string.Format(T("Seite {0} / {1}", "Page {0} / {1}"), nr + 1, seiten);
        }
        else
        {
            seitenZahl.Text = string.Format(T("Blatt {0} / {1}", "Sheet {0} / {1}"), vorschauPos + 1, blaetter);
        }
    }

    internal void VorschauLaden()
    {
        NavAktualisieren();
        if (auftrag.Count == 0) return;
        int proBlatt = SeitenProBlatt;
        int blaetter = BlattAnzahl();
        int basis = vorschauPos * proBlatt;   // vorschauPos ist ein BLATT-Index
        // Vorschau-DPI je N-up-Stufe: 16 Seiten je 200 dpi waeren ~250 MB
        // RAM je Blatt - die Zellen sind klein, weniger Aufloesung reicht.
        // 1-up bleibt 200 (auf 150-%-Monitoren war 150 sichtbar koernig)
        int dpi = proBlatt switch { 1 => 200, 2 => 150, 4 => 120, 6 => 100, 9 => 80, _ => 70 };
        var eigene = new List<Image>();
        try
        {
            // Seiten in der Stufen-DPI im gewaehlten annots-Modus holen, dann
            // auf das ECHTE Blatt komponiert - die Vorschau ist der Druck
            var alt = vorschau.Image;
            var teile = new List<(Image bild, double bPt, double hPt)>();
            for (int i = basis; i < auftrag.Count && i < basis + proBlatt; i++)
            {
                int nr = auftrag[i];
                var roh = seiteBild(nr, dpi, mitAnnots.Checked);
                eigene.Add(roh);
                teile.Add((roh, masse[nr][0], masse[nr][1]));
            }
            vorschau.Image = BlattAnsicht(teile);
            alt?.Dispose();
            ZoomAnwenden();
            vorschauInfo.Text = proBlatt == 1
                ? string.Format(
                    T("Vorschau · Druckauftrag: {0} {1} · Strg+Mausrad zoomt",
                      "Preview · print job: {0} {1} · Ctrl+wheel zooms"),
                    auftrag.Count, T(auftrag.Count == 1 ? "Seite" : "Seiten", auftrag.Count == 1 ? "page" : "pages"))
                : string.Format(
                    T("Vorschau · Druckauftrag: {0} {1} auf {2} {3} · Strg+Mausrad zoomt",
                      "Preview · print job: {0} {1} on {2} {3} · Ctrl+wheel zooms"),
                    auftrag.Count, T(auftrag.Count == 1 ? "Seite" : "Seiten", auftrag.Count == 1 ? "page" : "pages"),
                    blaetter, T(blaetter == 1 ? "Blatt" : "Blätter", blaetter == 1 ? "sheet" : "sheets"));
        }
        catch (Exception ex)
        {
            vorschau.Image = null;
            vorschauInfo.Text = T("Vorschau nicht möglich: ", "Preview unavailable: ") + ex.Message;
        }
        finally
        {
            foreach (var roh in eigene) roh.Dispose();
        }
    }

    private void ZoomAnwenden()
    {
        if (vorschau.Image == null) return;
        if (zoomF <= 0)
        {
            vorschau.Dock = DockStyle.Fill;
            vorschau.SizeMode = PictureBoxSizeMode.Zoom;
            zoomLabel.Text = T("Angepasst", "Fit");
            return;
        }
        vorschau.Dock = DockStyle.None;
        vorschau.SizeMode = PictureBoxSizeMode.Zoom;
        var img = vorschau.Image;
        double basis = Math.Min((double)zpanel.ClientSize.Width / img.Width,
                                (double)zpanel.ClientSize.Height / img.Height);
        double gesamt = basis * zoomF;
        vorschau.Size = new Size(Math.Max(40, (int)Math.Round(img.Width * gesamt)),
                                 Math.Max(40, (int)Math.Round(img.Height * gesamt)));
        vorschau.Location = new Point(0, 0);
        zoomLabel.Text = Math.Round(zoomF * 100) + " %";
    }

    // ---------------------------------------------------------------- Treiber-Eigenschaften
    /// <summary>Oeffnet den Eigenschaften-Dialog des DRUCKERTREIBERS (Papier-
    /// format, Qualitaet, Farbe ...) und wendet die Auswahl auf die Druck-
    /// einstellungen an. Abbruch laesst alles unberuehrt. Duplex, Papierformat
    /// UND Ausrichtung werden zurueckgelesen (in unsere Combos) und die
    /// Vorschau aktualisiert - sonst bliebe sie auf dem alten Blatt stehen
    /// (Nutzer-Fund: "Querformat im Treiberdialog sieht man in der Vorschau
    /// nicht").</summary>
    internal void TreiberEigenschaftenZeigen()
    {
        string? name = drucker.SelectedItem as string;
        if (string.IsNullOrEmpty(name)) return;
        try
        {
            IntPtr hDev = druckerEinstellungen.GetHdevmode();
            IntPtr pDev = GlobalLock(hDev);
            try
            {
                OpenPrinter(name, out var hPrn, IntPtr.Zero);
                try
                {
                    // DM_IN_BUFFER|DM_OUT_BUFFER|DM_IN_PROMPT: bestehende Werte
                    // vorbelegen, Dialog zeigen, Aenderungen zurueckschreiben
                    const int mode = 8 | 2 | 4;
                    if (DocumentProperties(Handle, hPrn, name, pDev, pDev, mode) == 1)   // IDOK
                    {
                        druckerEinstellungen.SetHdevmode(hDev);
                        DuplexComboVonTreiber(druckerEinstellungen.Duplex);
                        PapierSynchronisieren();        // Papierformat uebernehmen
                        AusrichtungSynchronisieren();   // Hoch/Quer uebernehmen
                        VorschauVerzoegertStarten();    // Vorschau folgt dem Treiber
                    }
                }
                finally { if (hPrn != IntPtr.Zero) ClosePrinter(hPrn); }
            }
            finally { GlobalUnlock(hDev); GlobalFree(hDev); }
        }
        catch
        {
            // Treiber ohne Eigenschaften-Dialog/fehlgeschlagener Aufruf:
            // still uebergehen - der Druck funktioniert weiterhin
        }
    }

    /// <summary>Duplex-Auswahl aus Treiber-Einstellungen in unsere Combo
    /// uebernehmen (intern fuer den kopflosen Test).</summary>
    internal void DuplexComboVonTreiber(Duplex d)
    {
        duplex.SelectedIndex = d switch
        {
            Duplex.Vertical => 1,      // Kante lang
            Duplex.Horizontal => 2,    // Kante kurz
            _ => 0,
        };
    }

    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool OpenPrinter(string name, out IntPtr hPrinter, IntPtr noh);

    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool ClosePrinter(IntPtr hPrinter);

    [DllImport("winspool.drv", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int DocumentProperties(IntPtr hwnd, IntPtr hPrinter, string geraet,
        IntPtr devModeOutput, IntPtr devModeInput, int mode);

    [DllImport("kernel32.dll")]
    private static extern IntPtr GlobalLock(IntPtr h);

    [DllImport("kernel32.dll")]
    private static extern bool GlobalUnlock(IntPtr h);

    [DllImport("kernel32.dll")]
    private static extern bool GlobalFree(IntPtr h);

    // ---------------------------------------------------------------- Fensterchrom
    private void EckenRunden()
    {
        try
        {
            int rund = 2;   // DWMWCP_ROUND
            _ = DwmSetWindowAttribute(Handle, 33, ref rund, sizeof(int));
            int keine = unchecked((int)0xFFFFFFFE);   // DWMWA_BORDER_COLOR NONE
            _ = DwmSetWindowAttribute(Handle, 34, ref keine, sizeof(int));
        }
        catch { /* Win10: eckig, unschädlich */ }
    }

    private const int WM_NCLBUTTONDOWN = 0xA1;
    private const int HTCAPTION = 2;

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, int wParam, int lParam);

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribut, ref int wert, int groesse);
}
