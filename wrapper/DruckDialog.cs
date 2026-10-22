using System.Drawing.Printing;

namespace FederPDF;

/// <summary>Eigener Druckdialog mit VORSCHAU (Nutzer-Rueckmeldung 22.10.2026:
/// "es war keine Druckvorschau zu sehen" - der WinForms-Standarddialog zeigt
/// nur Drucker/Optionen und fragt beim Aufgehen den Status von Netzwerk-
/// druckern ab, was an schlafenden WLAN-Druckern die UI fuer Dutzende Sekunden
/// blockieren kann). Links die gewaehlte Seite als Vorschau (aus dem echten
/// Druckinhalt inkl. Annotationen), rechts Drucker, Bereich, Kopien.
/// Zeigt modal; Ok liefert die Einstellungen, null heisst Abbruch.</summary>
internal sealed class DruckDialog : Form
{
    private readonly int seiten;
    private readonly List<int> auftrag;          // 0-basierte Seiten des Drucks
    private readonly Func<int, int, Image> seiteBild;   // (nr, dpi) -> Vorschau
    private readonly string spr;

    private readonly PictureBox vorschau;
    private readonly ComboBox drucker;
    private readonly RadioButton alles, aktuelle, bereich;
    private readonly NumericUpDown von, bis, kopien;
    private readonly Button zurueck, weiter, drucken;
    private readonly Label seitenLabel, vorschauInfo;
    private readonly int startSeite;             // 1-basiert, aus der UI
    private int vorschauPos;                     // Index in auftrag

    private static Color Hinter => Color.FromArgb(23, 25, 29);    // #17191d
    private static Color Flaeche => Color.FromArgb(44, 49, 58);   // #2c313a
    private static Color Schrift => Color.FromArgb(230, 233, 238);
    private static Color Gedämpft => Color.FromArgb(151, 160, 175);
    private static Color Akzent => Color.FromArgb(76, 194, 255);  // #4cc2ff

    private string T(string de, string en) => spr == "en" ? en : de;

    public string GewaehlterDrucker => drucker.SelectedItem as string ?? "";
    public int Kopien => (int)kopien.Value;
    public List<int> SeitenListe => auftrag;

    public DruckDialog(int seitenAnzahl, int aktuelleSeite, Func<int, int, Image> bildLader, string uiSprache)
    {
        seiten = seitenAnzahl;
        seiteBild = bildLader;
        spr = uiSprache;

        Text = T("Drucken", "Print");
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false; MinimizeBox = false;
        ShowInTaskbar = false;
        StartPosition = FormStartPosition.CenterParent;
        BackColor = Hinter;
        ForeColor = Schrift;
        Font = new Font("Segoe UI", 9.5f);
        ClientSize = new Size(760, 560);

        // ---------- links: Vorschau ----------
        var papier = new Panel
        {
            Location = new Point(16, 16),
            Size = new Size(470, 470),
            BackColor = Flaeche,
            Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left
        };
        vorschau = new PictureBox
        {
            SizeMode = PictureBoxSizeMode.Zoom,
            BackColor = Color.White,
            Location = new Point(15, 15),
            Size = new Size(440, 440),
            Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left
        };
        papier.Controls.Add(vorschau);
        Controls.Add(papier);

        vorschauInfo = new Label
        {
            Location = new Point(16, 494),
            Size = new Size(470, 20),
            ForeColor = Gedämpft,
            TextAlign = ContentAlignment.MiddleCenter,
            Anchor = AnchorStyles.Bottom | AnchorStyles.Left
        };
        Controls.Add(vorschauInfo);

        zurueck = new Button { Text = "◀", Size = new Size(40, 28), Location = new Point(150, 520), Anchor = AnchorStyles.Bottom | AnchorStyles.Left };
        weiter = new Button { Text = "▶", Size = new Size(40, 28), Location = new Point(310, 520), Anchor = AnchorStyles.Bottom | AnchorStyles.Left };
        seitenLabel = new Label { Size = new Size(120, 28), Location = new Point(190, 520), TextAlign = ContentAlignment.MiddleCenter, Anchor = AnchorStyles.Bottom | AnchorStyles.Left };
        zurueck.Click += (_, _) => Blaettern(-1);
        weiter.Click += (_, _) => Blaettern(1);
        Controls.Add(zurueck); Controls.Add(weiter); Controls.Add(seitenLabel);

        // ---------- rechts: Einstellungen ----------
        int rx = 502, rw = 242;

        Controls.Add(new Label { Text = T("Drucker", "Printer"), Location = new Point(rx, 16), Size = new Size(rw, 22) });
        drucker = new ComboBox
        {
            Location = new Point(rx, 40),
            Size = new Size(rw, 24),
            DropDownStyle = ComboBoxStyle.DropDownList,
            BackColor = Flaeche, ForeColor = Schrift
        };
        try
        {
            // NUR die Namen - kein Status-/Capability-Abfragen: genau die
            // blockiert an schlafenden Netzwerkdruckern (Nutzer-HP im Ruhemodus)
            foreach (string p in PrinterSettings.InstalledPrinters) drucker.Items.Add(p);
            string def = "";
            try { def = new PrinterSettings().PrinterName; } catch { }
            int i = def.Length > 0 ? drucker.Items.IndexOf(def) : -1;
            drucker.SelectedIndex = i >= 0 ? i : (drucker.Items.Count > 0 ? 0 : -1);
        }
        catch { }
        Controls.Add(drucker);

        int y = 84;
        alles = new RadioButton { Text = T("Alle Seiten", "All pages"), Location = new Point(rx, y), Size = new Size(rw, 24), ForeColor = Schrift };
        aktuelle = new RadioButton { Text = T("Aktuelle Seite", "Current page"), Location = new Point(rx, y += 28), Size = new Size(rw, 24), ForeColor = Schrift };
        bereich = new RadioButton { Text = T("Seitenbereich:", "Page range:"), Location = new Point(rx, y += 28), Size = new Size(rw, 24), ForeColor = Schrift };
        Controls.Add(alles); Controls.Add(aktuelle); Controls.Add(bereich);

        var vonL = new Label { Text = T("von", "from"), Location = new Point(rx + 8, y += 30), Size = new Size(38, 22), ForeColor = Gedämpft };
        von = new NumericUpDown { Location = new Point(rx + 50, y - 2), Size = new Size(66, 24), Minimum = 1, Maximum = seiten, Value = 1 };
        var bisL = new Label { Text = T("bis", "to"), Location = new Point(rx + 126, y), Size = new Size(30, 22), ForeColor = Gedämpft };
        bis = new NumericUpDown { Location = new Point(rx + 160, y - 2), Size = new Size(66, 24), Minimum = 1, Maximum = seiten, Value = seiten };
        Controls.Add(vonL); Controls.Add(von); Controls.Add(bisL); Controls.Add(bis);

        Controls.Add(new Label { Text = T("Kopien", "Copies"), Location = new Point(rx, y += 38), Size = new Size(rw, 22) });
        kopien = new NumericUpDown { Location = new Point(rx, y += 24), Size = new Size(80, 24), Minimum = 1, Maximum = 99, Value = 1 };
        Controls.Add(kopien);

        alles.CheckedChanged += (_, _) => AuftragNeu();
        aktuelle.CheckedChanged += (_, _) => AuftragNeu();
        bereich.CheckedChanged += (_, _) => AuftragNeu();
        von.ValueChanged += (_, _) => { if (von.Value > bis.Value) bis.Value = von.Value; AuftragNeu(); };
        bis.ValueChanged += (_, _) => { if (bis.Value < von.Value) von.Value = bis.Value; AuftragNeu(); };

        // ---------- Knöpfe ----------
        drucken = new Button
        {
            Text = T("Drucken", "Print"),
            Size = new Size(116, 34),
            Location = new Point(rx, ClientSize.Height - 50),
            Anchor = AnchorStyles.Bottom | AnchorStyles.Right,
            BackColor = Akzent,
            ForeColor = Color.FromArgb(18, 22, 28),
            FlatStyle = FlatStyle.Flat
        };
        drucken.FlatAppearance.BorderSize = 0;
        var abbruch = new Button
        {
            Text = T("Abbrechen", "Cancel"),
            Size = new Size(116, 34),
            Location = new Point(rx + 126, ClientSize.Height - 50),
            Anchor = AnchorStyles.Bottom | AnchorStyles.Right,
            BackColor = Flaeche,
            ForeColor = Schrift,
            FlatStyle = FlatStyle.Flat
        };
        abbruch.FlatAppearance.BorderSize = 0;
        drucken.DialogResult = DialogResult.OK;
        abbruch.DialogResult = DialogResult.Cancel;
        Controls.Add(drucken); Controls.Add(abbruch);
        CancelButton = abbruch;
        AcceptButton = drucken;

        // Start: alle Seiten. WICHTIG: auftrag VOR dem ersten Checked-Wechsel
        // initialisieren - CheckedChanged feuert AuftragNeu() synchron
        // (NullReference-Fund 22.10.2026: erst Checked, dann new List -> NRE).
        startSeite = Math.Max(1, Math.Min(aktuelleSeite, seiten));
        auftrag = new List<int>();
        alles.Checked = true;
        AuftragNeu();
        Load += (_, _) => VorschauZeigen();
    }

    /// <summary>Seitenliste des Druckauftrags aus dem gewaehlten Bereich bauen.</summary>
    private void AuftragNeu()
    {
        auftrag.Clear();
        if (aktuelle.Checked)
        {
            auftrag.Add(startSeite - 1);
        }
        else if (bereich.Checked)
        {
            for (int p = (int)von.Value; p <= (int)bis.Value; p++) auftrag.Add(p - 1);
        }
        else
        {
            for (int p = 1; p <= seiten; p++) auftrag.Add(p - 1);
        }
        vorschauPos = 0;
        if (IsHandleCreated) VorschauZeigen();
    }

    /// <summary>Aktuelle Seite voreinstellen (vom Aufrufer nach dem Konstruktor).</summary>
    public void AktuelleSeiteVoreinstellen(int seite1basiert)
    {
        von.Value = Math.Max(1, Math.Min(seite1basiert, seiten));
        bis.Value = von.Value;
        aktuelle.Checked = true;
    }

    private void Blaettern(int delta)
    {
        if (auftrag.Count == 0) return;
        vorschauPos = Math.Max(0, Math.Min(auftrag.Count - 1, vorschauPos + delta));
        VorschauZeigen();
    }

    private void VorschauZeigen()
    {
        zurueck.Enabled = vorschauPos > 0;
        weiter.Enabled = vorschauPos < auftrag.Count - 1;
        if (auftrag.Count == 0)
        {
            vorschau.Image = null;
            seitenLabel.Text = "-";
            vorschauInfo.Text = T("Keine Seiten gewählt.", "No pages selected.");
            return;
        }
        seitenLabel.Text = string.Format(T("Seite {0} von {1}", "Page {0} of {1}"), vorschauPos + 1, auftrag.Count);
        int nr = auftrag[vorschauPos];
        try
        {
            var alt = vorschau.Image;
            vorschau.Image = seiteBild(nr, 96);
            alt?.Dispose();
            vorschauInfo.Text = string.Format(
                T("Vorschau: Seite {0} von {1} (Druckauftrag: {2} Seiten)",
                  "Preview: page {0} of {1} ({2} pages in the print job)"),
                nr + 1, seiten, auftrag.Count);
        }
        catch (Exception ex)
        {
            vorschau.Image = null;
            vorschauInfo.Text = T("Vorschau nicht möglich: ", "Preview unavailable: ") + ex.Message;
        }
    }
}
