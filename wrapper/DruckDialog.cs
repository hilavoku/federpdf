using System.Drawing.Printing;
using System.Runtime.InteropServices;

namespace FederPDF;

/// <summary>Druckdialog im PDFgear-Stil: GROSSE Seitenvorschau links
/// (blätterbar, aus dem echten Druckinhalt), Einstellungsspalte rechts mit
/// Drucker, Kopien, Seitenbereich, "Signaturen/Markierungen/Formulare drucken"
/// (Nutzer-Wunsch: auch OHNE druckbar), Duplex und Skalierung (Nutzer-Wunsch
/// nach PDFgear-Vorbild). Folgt dem App-Theme (hell/dunkel, Farben aus der
/// Web-UI). Rahmenlos wie das Hauptfenster (eigene Titelzeile, DWM-Rundung).
/// DPI: KEIN WinForms-AutoScale (erstellte den Dialog im Owner-DPI-Kontext und
/// reskalierte ihn bei DPI-Wechsel physisch, 144→96 = 2/3, Mess-Fund
/// 22.10.2026) — stattdessen wird das Layout mit dem Owner-DPI-Faktor gebaut
/// und das Fenster per StartPosition.Manual direkt am Zielort erstellt.</summary>
internal sealed class DruckDialog : Form
{
    private readonly int seiten;
    private readonly List<int> auftrag;          // 0-basierte Seiten des Drucks
    private readonly Func<int, int, bool, Image> seiteBild;   // (nr, dpi, annots)
    private readonly string spr;
    private readonly int startSeite;             // 1-basiert, aus der UI
    private readonly float f;                    // DPI-Faktor (dpi/96), s. S()

    // Theme-Paletten (Farben aus der Web-UI: body / body.light)
    private readonly bool hell;
    private readonly Color bg, spalteFarbe, feld, papier, textFarbe, muted, akzent, akzentText, akzentHover;

    private readonly PictureBox vorschau;
    private readonly ComboBox drucker, duplex, skalierung;
    private readonly RadioButton alles, aktuelle, bereich;
    private readonly NumericUpDown von, bis, kopien, prozent;
    private readonly Button zurueck, weiter, drucken, abbruch;
    private readonly CheckBox mitAnnots;
    private readonly Label seitenZahl, vorschauInfo, prozentLabel;
    private readonly Panel prozentZeile;
    private int vorschauPos;                     // Index in auftrag

    private string T(string de, string en) => spr == "en" ? en : de;
    private int S(float v) => (int)Math.Round(v * f);
    private Font Ft(float pt, FontStyle stil = FontStyle.Regular)
        => new("Segoe UI", (float)Math.Round(pt * f, 1), stil);

    public string GewaehlterDrucker => drucker.SelectedItem as string ?? "";
    public int Kopien => (int)kopien.Value;
    public List<int> SeitenListe => auftrag;
    public bool MitAnnots => mitAnnots.Checked;
    public Duplex DuplexModus => duplex.SelectedIndex switch
    {
        1 => Duplex.Vertical,      // Kante lang
        2 => Duplex.Horizontal,    // Kante kurz
        _ => Duplex.Simplex,
    };
    /// <summary>skalierung 0 = einpassen; sonst Faktor (1,0 = tatsaechliche Groesse).</summary>
    public double Skalierung => skalierung.SelectedIndex switch
    {
        1 => 1.0,
        2 => (double)prozent.Value / 100.0,
        _ => 0.0,
    };

    /// <param name="dpi">DeviceDpi des Owner-Fensters (Layout-Skalierung).</param>
    /// <param name="hell">App-Theme (true = helles Design der Web-UI).</param>
    public DruckDialog(int seitenAnzahl, int aktuelleSeite, Func<int, int, bool, Image> bildLader,
                       string uiSprache, int dpi, bool hell)
    {
        seiten = seitenAnzahl;
        seiteBild = bildLader;
        spr = uiSprache;
        startSeite = Math.Max(1, Math.Min(aktuelleSeite, seiten));
        auftrag = new List<int>();
        f = Math.Max(1, dpi) / 96f;

        if (hell)
        {
            this.hell = true;
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
        ClientSize = new Size(S(1080), S(760));

        TitelzeileBauen();
        (vorschau, zurueck, weiter, seitenZahl, vorschauInfo) = VorschauBauen();
        (drucker, duplex, skalierung, alles, aktuelle, bereich, von, bis, kopien, prozent, prozentLabel,
         prozentZeile, mitAnnots, drucken, abbruch) = SpalteBauen();

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
        mitAnnots.CheckedChanged += (_, _) => VorschauZeigen();   // Vorschau = echter Druckinhalt
        skalierung.SelectedIndexChanged += (_, _) => prozentZeile.Visible = skalierung.SelectedIndex == 2;

        alles.Checked = true;
        AuftragNeu();
        Load += (_, _) => { EckenRunden(); VorschauZeigen(); };
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
    private (PictureBox, Button, Button, Label, Label) VorschauBauen()
    {
        var zone = new Panel
        {
            Location = new Point(0, S(48)),
            Size = new Size(S(748), ClientSize.Height - S(48)),
            BackColor = papier,
        };
        var bild = new PictureBox
        {
            SizeMode = PictureBoxSizeMode.Zoom,
            BackColor = Color.White,
            BorderStyle = BorderStyle.FixedSingle,
            Location = new Point(S(44), S(76)),
            Size = new Size(S(660), S(580)),
        };
        zone.Controls.Add(bild);

        var zr = new Button { Text = "\u2039", Font = Ft(15f), Size = new Size(S(44), S(34)), Location = new Point(S(308), ClientSize.Height - S(78)), FlatStyle = FlatStyle.Flat, BackColor = papier, ForeColor = textFarbe };
        var zv = new Button { Text = "\u203A", Font = Ft(15f), Size = new Size(S(44), S(34)), Location = new Point(S(396), ClientSize.Height - S(78)), FlatStyle = FlatStyle.Flat, BackColor = papier, ForeColor = textFarbe };
        zr.FlatAppearance.BorderSize = 0; zv.FlatAppearance.BorderSize = 0;
        zr.FlatAppearance.MouseOverBackColor = feld; zv.FlatAppearance.MouseOverBackColor = feld;

        var zahl = new Label
        {
            Text = "1 / 1",
            Font = Ft(10.5f),
            ForeColor = textFarbe,
            TextAlign = ContentAlignment.MiddleCenter,
            Size = new Size(S(84), S(34)),
            Location = new Point(S(332), ClientSize.Height - S(74)),
        };
        var info = new Label
        {
            Text = "",
            Font = Ft(8.25f),
            ForeColor = muted,
            TextAlign = ContentAlignment.MiddleCenter,
            Size = new Size(S(500), S(20)),
            Location = new Point(S(124), ClientSize.Height - S(40)),
        };
        zone.Controls.Add(zr); zone.Controls.Add(zv); zone.Controls.Add(zahl); zone.Controls.Add(info);
        Controls.Add(zone);
        return (bild, zr, zv, zahl, info);
    }

    // ---------------------------------------------------------------- Spalte rechts
    private (ComboBox, ComboBox, ComboBox, RadioButton, RadioButton, RadioButton,
             NumericUpDown, NumericUpDown, NumericUpDown, NumericUpDown, Label, Panel, CheckBox, Button, Button) SpalteBauen()
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
        y += S(34 + 20);

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
        return (cb, du, sk, ra, rk, rb, vn, bs, ko, pzFeld, pzL, pz, chk, ok, ab);
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
            // Vorschau in MONITORDPI (geklemmt 96..192), im gewaehlten annots-
            // Modus - sie zeigt immer den ECHTEN Druckinhalt
            int dpi = Math.Max(96, Math.Min(DeviceDpi, 192));
            var alt = vorschau.Image;
            vorschau.Image = seiteBild(nr, dpi, mitAnnots.Checked);
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
