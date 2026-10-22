using System.Drawing.Printing;
using System.Runtime.InteropServices;

namespace FederPDF;

/// <summary>Druckdialog im PDFgear-Stil (Nutzer-Wunsch 22.10.2026): GROSSE
/// Seitenvorschau links (blätterbar, aus dem echten Druckinhalt inkl.
/// Annotationen), dunkle Einstellungsspalte rechts (Drucker, Kopien,
/// Seitenbereich mit Seitenzahlen in den Optionen). Rahmenlos wie das
/// Hauptfenster (eigene Titelzeile, DWM-Rundung).
/// DPI: KEIN WinForms-AutoScale — das erstellte den Dialog im DPI-Kontext des
/// Owners, überschrieb die gepinnte 96-Basislinie und reskalierte bei einem
/// DPI-Wechsel nach der Erstellung die Fensterfläche physisch (144→96 =
/// 2/3-Verkleinerung, Mess-Fund 22.10.2026). Stattdessen deterministisch wie
/// das Hauptfenster: Layout wird mit dem ÜBERGEBENEN Owner-DPI-Faktor gebaut
/// und das Fenster per StartPosition.Manual direkt am Zielort erstellt — kein
/// DPI-Wechsel, keine Überraschungen.</summary>
internal sealed class DruckDialog : Form
{
    private readonly int seiten;
    private readonly List<int> auftrag;          // 0-basierte Seiten des Drucks
    private readonly Func<int, int, Image> seiteBild;   // (nr, dpi) -> Bild
    private readonly string spr;
    private readonly int startSeite;             // 1-basiert, aus der UI
    private readonly float f;                    // DPI-Faktor (dpi/96), s. S()

    private readonly PictureBox vorschau;
    private readonly ComboBox drucker;
    private readonly RadioButton alles, aktuelle, bereich;
    private readonly NumericUpDown von, bis, kopien;
    private readonly Button zurueck, weiter, drucken, abbruch;
    private readonly Label seitenZahl, vorschauInfo;
    private int vorschauPos;                     // Index in auftrag

    private static Color Hint => Color.FromArgb(23, 25, 29);       // #17191d App-Hintergrund
    private static Color Spalte => Color.FromArgb(28, 31, 36);     // Einstellungsspalte
    private static Color Flaeche => Color.FromArgb(44, 49, 58);    // #2c313a Felder/Knöpfe
    private static Color Papier => Color.FromArgb(33, 37, 43);     // Vorschau-Zone
    private static Color Schrift => Color.FromArgb(230, 233, 238); // #e6e9ee
    private static Color Gedaempft => Color.FromArgb(151, 160, 175); // #97a0af
    private static Color Akzent => Color.FromArgb(76, 194, 255);   // #4cc2ff

    private string T(string de, string en) => spr == "en" ? en : de;
    private int S(float v) => (int)Math.Round(v * f);
    private Font Ft(float pt, FontStyle stil = FontStyle.Regular)
        => new("Segoe UI", (float)Math.Round(pt * f, 1), stil);
    private Font FtFett(float pt) => Ft(pt, FontStyle.Bold);

    public string GewaehlterDrucker => drucker.SelectedItem as string ?? "";
    public int Kopien => (int)kopien.Value;
    public List<int> SeitenListe => auftrag;

    /// <param name="dpi">DeviceDpi des Owner-Fensters (steuert die Layout-Skalierung).</param>
    public DruckDialog(int seitenAnzahl, int aktuelleSeite, Func<int, int, Image> bildLader,
                       string uiSprache, int dpi)
    {
        seiten = seitenAnzahl;
        seiteBild = bildLader;
        spr = uiSprache;
        startSeite = Math.Max(1, Math.Min(aktuelleSeite, seiten));
        auftrag = new List<int>();
        f = Math.Max(1, dpi) / 96f;

        Text = T("Drucken", "Print");
        FormBorderStyle = FormBorderStyle.None;
        MaximizeBox = false; MinimizeBox = false;
        ShowInTaskbar = false;
        BackColor = Hint;
        ForeColor = Schrift;
        Font = Ft(9.5f);
        ClientSize = new Size(S(1080), S(700));

        TitelzeileBauen();
        (vorschau, zurueck, weiter, seitenZahl, vorschauInfo) = VorschauBauen();
        (drucker, alles, aktuelle, bereich, von, bis, kopien, drucken, abbruch) = SpalteBauen();

        drucken.Click += (_, _) => { DialogResult = DialogResult.OK; Close(); };
        abbruch.Click += (_, _) => { DialogResult = DialogResult.Cancel; Close(); };
        AcceptButton = drucken;
        CancelButton = abbruch;
        zurueck.Click += (_, _) => Blaettern(-1);
        weiter.Click += (_, _) => Blaettern(1);
        vorschau.MouseClick += (_, e) => { if (e.Button == MouseButtons.Left) vorschau.Select(); };
        vorschau.MouseWheel += (s, e) => { if (auftrag.Count > 1) { Blaettern(e.Delta > 0 ? -1 : 1); ((HandledMouseEventArgs)e).Handled = true; } };
        alles.CheckedChanged += (_, _) => AuftragNeu();
        aktuelle.CheckedChanged += (_, _) => AuftragNeu();
        bereich.CheckedChanged += (_, _) => AuftragNeu();
        von.ValueChanged += (_, _) => { if (von.Value > bis.Value) bis.Value = von.Value; AuftragNeu(); };
        bis.ValueChanged += (_, _) => { if (bis.Value < von.Value) von.Value = bis.Value; AuftragNeu(); };

        alles.Checked = true;
        AuftragNeu();
        Load += (_, _) => { EckenRunden(); VorschauZeigen(); };
    }

    /// <summary>Auf dem Owner zentrieren und per StartPosition.Manual direkt
    /// dort erstellen — der Dialog entsteht damit im DPI-Kontext des Owners
    /// und erfährt keinen DPI-Wechsel nach der Erstellung.</summary>
    public void ZentrierenAuf(Form owner)
    {
        StartPosition = FormStartPosition.Manual;
        Location = new Point(owner.Left + (owner.Width - Width) / 2,
                             Math.Max(owner.Top, owner.Top + (owner.Height - Height) / 2));
    }

    // ---------------------------------------------------------------- Titelzeile
    private void TitelzeileBauen()
    {
        var leiste = new Panel { Dock = DockStyle.Top, Height = S(48), BackColor = Hint };
        var titelText = new Label
        {
            Text = T("Drucken", "Print"),
            Font = Ft(12.5f, FontStyle.Bold),
            ForeColor = Schrift,
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
            BackColor = Hint,
            ForeColor = Gedaempft,
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
    private (PictureBox, Button, Button, Label, Label) VorschauBauen()
    {
        var zone = new Panel
        {
            Location = new Point(0, S(48)),
            Size = new Size(S(748), ClientSize.Height - S(48)),
            BackColor = Papier,
        };
        var bild = new PictureBox
        {
            SizeMode = PictureBoxSizeMode.Zoom,
            BackColor = Color.White,
            BorderStyle = BorderStyle.FixedSingle,
            Location = new Point(S(44), S(76)),
            Size = new Size(S(660), S(520)),
            Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right,
        };
        zone.Controls.Add(bild);

        var zr = new Button { Text = "\u2039", Font = Ft(15f), Size = new Size(S(44), S(34)), Location = new Point(S(308), ClientSize.Height - S(78)), FlatStyle = FlatStyle.Flat, BackColor = Papier, ForeColor = Schrift, Anchor = AnchorStyles.Bottom };
        var zv = new Button { Text = "\u203A", Font = Ft(15f), Size = new Size(S(44), S(34)), Location = new Point(S(396), ClientSize.Height - S(78)), FlatStyle = FlatStyle.Flat, BackColor = Papier, ForeColor = Schrift, Anchor = AnchorStyles.Bottom };
        zr.FlatAppearance.BorderSize = 0; zv.FlatAppearance.BorderSize = 0;
        zr.FlatAppearance.MouseOverBackColor = Flaeche; zv.FlatAppearance.MouseOverBackColor = Flaeche;

        var zahl = new Label
        {
            Text = "1 / 1",
            Font = Ft(10.5f),
            ForeColor = Schrift,
            TextAlign = ContentAlignment.MiddleCenter,
            Size = new Size(S(84), S(34)),
            Location = new Point(S(332), ClientSize.Height - S(74)),
            Anchor = AnchorStyles.Bottom,
        };
        var info = new Label
        {
            Text = "",
            Font = Ft(8.25f),
            ForeColor = Gedaempft,
            TextAlign = ContentAlignment.MiddleCenter,
            Size = new Size(S(500), S(20)),
            Location = new Point(S(124), ClientSize.Height - S(40)),
            Anchor = AnchorStyles.Bottom,
        };
        zone.Controls.Add(zr); zone.Controls.Add(zv); zone.Controls.Add(zahl); zone.Controls.Add(info);
        Controls.Add(zone);
        return (bild, zr, zv, zahl, info);
    }

    // ---------------------------------------------------------------- Spalte rechts
    private (ComboBox, RadioButton, RadioButton, RadioButton, NumericUpDown, NumericUpDown, NumericUpDown, Button, Button) SpalteBauen()
    {
        int rand = S(26), fw = S(332) - rand * 2;   // Innenrand, Feldbreite
        var spalte = new Panel
        {
            Location = new Point(S(748), S(48)),
            Size = new Size(S(332), ClientSize.Height - S(48)),
            BackColor = Spalte,
        };

        int y = S(24);
        spalte.Controls.Add(Caption(T("Drucker", "Printer"), ref y, rand));
        var cb = new ComboBox
        {
            Location = new Point(rand, y),
            Size = new Size(fw, S(34)),
            DropDownStyle = ComboBoxStyle.DropDownList,
            FlatStyle = FlatStyle.Flat,
            BackColor = Flaeche,
            ForeColor = Schrift,
            Font = Ft(10f),
        };
        try
        {
            // NUR Namen - KEINE Statusabfragen: die blockieren an schlafenden
            // Netzwerkdruckern (Nutzer-HP im Ruhemodus) die Dialog-Anzeige
            foreach (string p in PrinterSettings.InstalledPrinters) cb.Items.Add(p);
            string def = "";
            try { def = new PrinterSettings().PrinterName; } catch { }
            int i = def.Length > 0 ? cb.Items.IndexOf(def) : -1;
            cb.SelectedIndex = i >= 0 ? i : (cb.Items.Count > 0 ? 0 : -1);
        }
        catch { }
        spalte.Controls.Add(cb);
        y += S(34 + 22);

        spalte.Controls.Add(Caption(T("Kopien", "Copies"), ref y, rand));
        var ko = new NumericUpDown
        {
            Location = new Point(rand, y),
            Size = new Size(S(120), S(32)),
            Minimum = 1, Maximum = 99, Value = 1,
            BackColor = Flaeche,
            ForeColor = Schrift,
            BorderStyle = BorderStyle.None,
            Font = Ft(10.5f),
            TextAlign = HorizontalAlignment.Center,
        };
        spalte.Controls.Add(ko);
        y += S(32 + 24);

        spalte.Controls.Add(Caption(T("Seiten", "Pages"), ref y, rand));
        y += S(6);
        var ra = Radio(string.Format(T("Alle Seiten ({0})", "All pages ({0})"), seiten), ref y, rand);
        var rk = Radio(string.Format(T("Aktuelle Seite ({0})", "Current page ({0})"), startSeite), ref y, rand);
        var rb = Radio(T("Seitenbereich", "Page range"), ref y, rand);
        spalte.Controls.Add(ra); spalte.Controls.Add(rk); spalte.Controls.Add(rb);
        y += S(8);

        var vonL = new Label { Text = T("von", "from"), Font = Ft(9f), ForeColor = Gedaempft, AutoSize = true, Location = new Point(rand + S(28), y + S(6)) };
        var vn = new NumericUpDown
        {
            Location = new Point(rand + S(66), y),
            Size = new Size(S(88), S(30)),
            Minimum = 1, Maximum = seiten, Value = 1,
            BackColor = Flaeche, ForeColor = Schrift, BorderStyle = BorderStyle.None,
            Font = Ft(10f),
            TextAlign = HorizontalAlignment.Center,
        };
        var bisL = new Label { Text = T("bis", "to"), Font = Ft(9f), ForeColor = Gedaempft, AutoSize = true, Location = new Point(rand + S(164), y + S(6)) };
        var bs = new NumericUpDown
        {
            Location = new Point(rand + S(196), y),
            Size = new Size(S(88), S(30)),
            Minimum = 1, Maximum = seiten, Value = seiten,
            BackColor = Flaeche, ForeColor = Schrift, BorderStyle = BorderStyle.None,
            Font = Ft(10f),
            TextAlign = HorizontalAlignment.Center,
        };
        spalte.Controls.Add(vonL); spalte.Controls.Add(vn); spalte.Controls.Add(bisL); spalte.Controls.Add(bs);
        y += S(30 + 18);

        var hinweis = new Label
        {
            Text = T("Der Ausdruck enthält Signaturen, Texte, Markierungen\nund ausgefüllte Formulare – auch ungespeicherte Änderungen.",
                     "The printout includes signatures, texts, markup\nand filled form fields – including unsaved changes."),
            Font = Ft(8.25f),
            ForeColor = Gedaempft,
            Location = new Point(rand, y),
            Size = new Size(fw, S(36)),
        };
        spalte.Controls.Add(hinweis);

        var ok = new Button
        {
            Text = T("Drucken", "Print"),
            Font = Ft(10.5f, FontStyle.Bold),
            Size = new Size(fw, S(46)),
            Location = new Point(rand, spalte.Height - S(26 + 46 + 10 + 36)),
            FlatStyle = FlatStyle.Flat,
            BackColor = Akzent,
            ForeColor = Color.FromArgb(18, 22, 28),
            Anchor = AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right,
        };
        ok.FlatAppearance.BorderSize = 0;
        ok.FlatAppearance.MouseOverBackColor = Color.FromArgb(120, 208, 255);
        var ab = new Button
        {
            Text = T("Abbrechen", "Cancel"),
            Font = Ft(10f),
            Size = new Size(fw, S(36)),
            Location = new Point(rand, spalte.Height - S(26 + 36)),
            FlatStyle = FlatStyle.Flat,
            BackColor = Flaeche,
            ForeColor = Schrift,
            Anchor = AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right,
        };
        ab.FlatAppearance.BorderSize = 0;
        ab.FlatAppearance.MouseOverBackColor = Color.FromArgb(58, 64, 74);
        spalte.Controls.Add(ok); spalte.Controls.Add(ab);

        spalte.Paint += (_, e) =>
        {
            using var stift = new Pen(Color.FromArgb(38, 42, 48));
            e.Graphics.DrawLine(stift, 0, 0, 0, spalte.Height);
        };

        Controls.Add(spalte);
        return (cb, ra, rk, rb, vn, bs, ko, ok, ab);
    }

    private Label Caption(string text, ref int y, int rand)
    {
        var l = new Label
        {
            Text = text.ToUpper(),
            Font = FtFett(8.25f),
            ForeColor = Gedaempft,
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
            ForeColor = Schrift,
            AutoSize = true,
            Location = new Point(rand, y),
        };
        y += S(32);
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
        if (IsHandleCreated) VorschauZeigen();
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
            seitenZahl.Text = "-";
            vorschauInfo.Text = T("Keine Seiten gewählt.", "No pages selected.");
            return;
        }
        int nr = auftrag[vorschauPos];
        seitenZahl.Text = string.Format(T("Seite {0} / {1}", "Page {0} / {1}"), nr + 1, seiten);
        try
        {
            // Vorschau in MONITORDPI (geklemmt 96..192) - auf dem 150-%-Notebook
            // war das 96-dpi-Bild sichtbar unscharf. Das ist der ECHTE Druck-
            // inhalt (Annotationen/Formulare), nicht die Ansicht-Ebene.
            int dpi = Math.Max(96, Math.Min(DeviceDpi, 192));
            var alt = vorschau.Image;
            vorschau.Image = seiteBild(nr, dpi);
            alt?.Dispose();
            vorschauInfo.Text = string.Format(
                T("Vorschau · Druckauftrag: {0} {1}", "Preview · print job: {0} {1}"),
                auftrag.Count, T(auftrag.Count == 1 ? "Seite" : "Seiten", auftrag.Count == 1 ? "page" : "pages"));
        }
        catch (Exception ex)
        {
            vorschau.Image = null;
            vorschauInfo.Text = T("Vorschau nicht möglich: ", "Preview unavailable: ") + ex.Message;
        }
    }

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
