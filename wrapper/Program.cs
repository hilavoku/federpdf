using Microsoft.Web.WebView2.WinForms;
using System.Diagnostics;
using System.Drawing.Drawing2D;
using System.Drawing.Printing;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text.Json;

namespace FederPDF;

internal static class Program
{
    private static int port;
    private static bool dirty;
    // UI-Sprache ("de"/"en"): Startwert aus einstellungen.json, laufend per
    // Webmessage "sprache|en" aus der UI nachgezogen (Splash/Dialoge)
    private static string uiSprache = "de";
    // UI-Theme (hell): Startwert aus einstellungen.json, laufend per
    // Webmessage "theme|light|dark" nachgezogen (Druckdialog palettiert mit)
    private static bool uiHell;
    // Gespeicherter Druck-Seitenrand (mm, Schlüssel "druckRandMm" in
    // einstellungen.json) und Position ("druckOben": true = kopfbuendig):
    // Startwerte beim Hochfahren lesen, nach jedem Druck-OK über /api/prefs
    // zurückschreiben (Server bleibt alleiniger Schreiber der Datei)
    private static double druckRandMm;
    private static bool druckOben;
    private static bool druckSw;   // true = schwarzweiß drucken

    [STAThread]
    private static void Main(string[] args)
    {
        // Doppelklick auf eine PDF-Datei: Pfad liegt in args[0]
        string? pdfPath = args.Length > 0 ? Path.GetFullPath(args[0]) : null;
        if (pdfPath != null && !File.Exists(pdfPath)) pdfPath = null;

        port = GetFreePort();
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        string serverExe = Path.Combine(baseDir, "server", "FederPDFServer.exe");
        if (!File.Exists(serverExe))
        {
            MessageBox.Show(
                "FederPDFServer.exe wurde nicht gefunden:\n" + serverExe,
                "FederPDF", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        // Gespeicherte UI-Sprache uebernehmen (steuert Splash/Fehlerseite/
        // Schliessdialog, bis die UI per "sprache|xx" nachzieht) + Start-Design
        // fuer den inneren Ziehzonen-Ring
        bool startLicht = false;
        try
        {
            string einst = Path.Combine(baseDir, "einstellungen.json");
            if (File.Exists(einst))
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(einst));
                if (doc.RootElement.TryGetProperty("sprache", out var sp)
                    && sp.ValueKind == JsonValueKind.String && sp.GetString() == "en")
                    uiSprache = "en";
                if (doc.RootElement.TryGetProperty("theme", out var th)
                    && th.ValueKind == JsonValueKind.String && th.GetString() == "light")
                    startLicht = true;
                if (doc.RootElement.TryGetProperty("druckRandMm", out var drm)
                    && drm.ValueKind == JsonValueKind.Number)
                    druckRandMm = Math.Clamp(drm.GetDouble(), 0, 50);
                if (doc.RootElement.TryGetProperty("druckOben", out var dob)
                    && (dob.ValueKind == JsonValueKind.True || dob.ValueKind == JsonValueKind.False))
                    druckOben = dob.GetBoolean();
                if (doc.RootElement.TryGetProperty("druckSw", out var dsw)
                    && (dsw.ValueKind == JsonValueKind.True || dsw.ValueKind == JsonValueKind.False))
                    druckSw = dsw.GetBoolean();
            }
        }
        catch { /* kaputte/kompatible Datei: Deutsch/Dunkel bleibt */ }
        uiHell = startLicht;

        var psi = new ProcessStartInfo
        {
            FileName = serverExe,
            Arguments = $"--port {port}" + (pdfPath != null ? $" --file \"{pdfPath}\"" : ""),
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = Path.GetDirectoryName(serverExe)!
        };
        Process? server = Process.Start(psi);

        ApplicationConfiguration.Initialize();

        // Fensterrand: SICHTBAR bleibt der duenne Trikolore-Streifen (4 px, Nutzer-
        // Wunsch v0.18.11); die ZIEHZONE ist breiter (nativen Rahmen nachempfunden,
        // Nutzer-Wunsch v0.21.4: Ecken besser greifbar) und wird in HauptForm
        // (RandAnwenden/OnPaint) DPI-abhaengig gesetzt und mit UI-Farben gefuellt.

        var form = new HauptForm
        {
            Text = pdfPath != null
                ? "FederPDF - " + Path.GetFileName(pdfPath)
                : "FederPDF",
            Width = 1450,
            Height = 940,
            StartPosition = FormStartPosition.CenterScreen,
            Font = new Font("Segoe UI", 9f),
            FormBorderStyle = FormBorderStyle.None,
            BackColor = System.Drawing.Color.FromArgb(23, 25, 29)
        };
        form.ThemeSetzen(startLicht);   // innerer Ziehzonen-Ring im gespeicherten Design

        // Fenstergroesse/-position wiederherstellen (fenster.json neben der EXE)
        string winFile = Path.Combine(baseDir, "fenster.json");
        try
        {
            if (File.Exists(winFile))
            {
                using var winDoc = JsonDocument.Parse(File.ReadAllText(winFile));
                var r = winDoc.RootElement;
                int wx = r.TryGetProperty("x", out var px) && px.ValueKind == JsonValueKind.Number ? px.GetInt32() : 100;
                int wy = r.TryGetProperty("y", out var py) && py.ValueKind == JsonValueKind.Number ? py.GetInt32() : 60;
                int ww = r.TryGetProperty("w", out var pw) && pw.ValueKind == JsonValueKind.Number ? Math.Max(400, pw.GetInt32()) : 1450;
                int wh = r.TryGetProperty("h", out var ph) && ph.ValueKind == JsonValueKind.Number ? Math.Max(300, ph.GetInt32()) : 940;
                bool wasMax = r.TryGetProperty("max", out var pm) && pm.ValueKind == JsonValueKind.True;
                var bounds = new Rectangle(wx, wy, ww, wh);
                if (Screen.AllScreens.Any(s => s.WorkingArea.IntersectsWith(bounds)))
                {
                    form.StartPosition = FormStartPosition.Manual;
                    form.Bounds = bounds;
                }
                if (wasMax) form.WindowState = FormWindowState.Maximized;
            }
        }
        catch { /* kaputte Datei: Standardgroesse und zentriert starten */ }
        var webView = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = System.Drawing.Color.FromArgb(23, 25, 29) };
        form.Controls.Add(webView);
        try { form.Icon = System.Drawing.Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

        form.Resize += (_, _) =>
        {
            // Padding (Ziehzone) pflegt HauptForm.RandAnwenden selbst (vor dem
            // Layout, im OnResize) - hier nur die WebView-Flaeche nachziehen
            WebViewAufInnenflaecheSetzen(form, webView);
        };

        form.Shown += (_, _) =>
        {
            // Nach dem ersten Anzeigen einmal explizit setzen: Beim Wiederherstellen
            // der Groesse aus fenster.json skaliert das automatische Dock das
            // WebView2 mit falscher DPI-Basis (Control dann nur CSS- statt
            // physischer Groesse) - Klicks landen daneben (DPI-De-Sync).
            WebViewAufInnenflaecheSetzen(form, webView);
        };

        form.Load += async (_, _) =>
        {
            try
            {
                await webView.EnsureCoreWebView2Async();
                webView.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
                webView.CoreWebView2.Settings.AreHostObjectsAllowed = false;
                webView.CoreWebView2.WebMessageReceived += async (_, e) =>
                {
                    var msg = e.TryGetWebMessageAsString();
                    if (msg == "dirty:1") dirty = true;
                    else if (msg == "dirty:0") dirty = false;
                    else if (msg != null && msg.StartsWith("sprache|")) uiSprache = msg.Substring(8) == "en" ? "en" : "de";
                    else if (msg != null && msg.StartsWith("url|"))
                    {
                        // Link aus der UI (Über-Dialog) im Standard-Browser oeffnen -
                        // nur http/https, nichts sonstiges
                        var adresse = msg.Substring(4);
                        if (Uri.TryCreate(adresse, UriKind.Absolute, out var ziel)
                            && (ziel.Scheme == Uri.UriSchemeHttp || ziel.Scheme == Uri.UriSchemeHttps))
                        {
                            try { Process.Start(new ProcessStartInfo { FileName = adresse, UseShellExecute = true }); }
                            catch { /* kein Browser/abgebrochen: still ignorieren */ }
                        }
                    }
                    else if (msg != null && msg.StartsWith("fenster|"))
                    {
                        // Eigene Titelleiste: Minimieren/Maximieren/Schliessen/Ziehen aus der Kopfzeile
                    var befehl = msg.Substring(8);
                    if (befehl == "min") form.WindowState = FormWindowState.Minimized;
                    else if (befehl == "max") form.MaximierenWechseln();
                    else if (befehl == "zu") form.Close();
                    else if (befehl == "drag") form.Titelziehen();
                    else if (befehl == "groesse") form.GroesseZiehen();
                        try
                        {
                            var maxed = form.WindowState == FormWindowState.Maximized;
                            _ = webView.CoreWebView2.ExecuteScriptAsync(
                                $"window.pwMaximiert && window.pwMaximiert({(maxed ? "true" : "false")});");
                        }
                        catch { /* UI evtl. nicht bereit */ }
                    }
                    else if (msg == "theme|light" || msg == "theme|dark")
                    {
                        // Fensterrand ist seit v0.16.9 in beiden Designs der
                        // Schwarz-Rot-Gold-Verlauf; der INNERE Ziehzone-Ring
                        // faerbt sich seit v0.21.4 passend zum Design
                        uiHell = msg == "theme|light";
                        form.ThemeSetzen(uiHell);
                    }
                    else if (msg != null && msg.StartsWith("druck|"))
                    {
                        // "druck|<did>|<aktuelleSeite1basiert>" - drittes Feld optional
                        var teile = msg.Split('|');
                        int aktuelle = teile.Length > 2 && int.TryParse(teile[2], out int p) ? p : 0;
                        await DruckenAsync(teile[1], aktuelle, webView);
                    }
                    else if (msg != null && msg.StartsWith("saveas|"))
                    {
                        // "saveas|<docid>|<dateiname>|<flatten>" -> Systemdialog, dann speichern
                        var teile = msg.Split('|', 4);
                        if (teile.Length >= 3)
                        {
                            int flatten = teile.Length == 4 && teile[3] == "1" ? 1 : 0;
                            using var dlg = new SaveFileDialog
                            {
                                Filter = "PDF-Datei (*.pdf)|*.pdf|Alle Dateien (*.*)|*.*",
                                FileName = teile[2].EndsWith(".pdf", StringComparison.OrdinalIgnoreCase)
                                    ? teile[2] : teile[2] + ".pdf"
                            };
                            if (dlg.ShowDialog() == DialogResult.OK)
                            {
                                bool ok = false;
                                try
                                {
                                    using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
                                    var resp = await http.GetAsync(
                                        $"http://127.0.0.1:{port}/api/saveas/{teile[1]}?path={Uri.EscapeDataString(dlg.FileName)}&flatten={flatten}");
                                    ok = resp.IsSuccessStatusCode;
                                }
                                catch { ok = false; }
                                try
                                {
                                    var script = $"window.pwSaveasDone && window.pwSaveasDone({(ok ? "true" : "false")}, {System.Text.Json.JsonSerializer.Serialize(dlg.FileName)});";
                                    await webView.CoreWebView2.ExecuteScriptAsync(script);
                                }
                                catch { /* UI ist evtl. schon zu */ }
                            }
                        }
                    }
                };

                // Erst den Startbildschirm zeigen - NIE die Edge-Fehlerseite
                webView.CoreWebView2.NavigateToString(SplashHtml());

                // Warten, bis der Server antwortet (max. ~60 s, Abbruch wenn er stirbt)
                bool ready = false;
                using (var http = new HttpClient { Timeout = TimeSpan.FromSeconds(2) })
                {
                    for (int i = 0; i < 120 && server is { HasExited: false }; i++)
                    {
                        try
                        {
                            var resp = await http.GetAsync($"http://127.0.0.1:{port}/api/health");
                            if (resp.IsSuccessStatusCode) { ready = true; break; }
                        }
                        catch { /* Server noch nicht bereit */ }
                        await Task.Delay(500);
                    }
                }

                if (ready)
                {
                    webView.CoreWebView2.Navigate($"http://127.0.0.1:{port}/");
                }
                else
                {
                    webView.CoreWebView2.NavigateToString(ErrorHtml());
                }
            }
            catch (Exception ex)
            {
                MessageBox.Show(
                    "WebView2 konnte nicht geladen werden:\n" + ex.Message +
                    "\n\nBitte das \"WebView2 Runtime\"-Paket installieren.",
                    "FederPDF", MessageBoxButtons.OK, MessageBoxIcon.Error);
                form.Close();
            }
        };

        form.FormClosing += (_, e) =>
        {
            if (!dirty) return;
            bool en = uiSprache == "en";
            var choice = MessageBox.Show(
                en ? "There are unsaved changes.\n\n" +
                     "Yes = Save and close\n" +
                     "No = Close without saving\n" +
                     "Cancel = Back to the document"
                   : "Es gibt nicht gespeicherte \u00c4nderungen.\n\n" +
                     "Ja = Speichern und schließen\n" +
                     "Nein = Ohne Speichern schließen\n" +
                     "Abbrechen = Zurück zum Dokument",
                en ? "Unsaved changes" : "Ungespeicherte \u00c4nderungen",
                MessageBoxButtons.YesNoCancel, MessageBoxIcon.Warning,
                MessageBoxDefaultButton.Button1);
            if (choice == DialogResult.Cancel)
            {
                e.Cancel = true;
                return;
            }
            if (choice == DialogResult.Yes)
            {
                if (!SaveCurrent())
                {
                    var again = MessageBox.Show(
                        en ? "Saving failed. Close anyway?" : "Speichern fehlgeschlagen. Trotzdem schließen?",
                        "FederPDF", MessageBoxButtons.YesNo, MessageBoxIcon.Error);
                    if (again == DialogResult.No) e.Cancel = true;
                }
            }
        };

        form.FormClosed += (_, _) =>
        {
            // Fenstergroesse/-position fuer den naechsten Start merken
            try
            {
                var state = form.WindowState;
                var b = state == FormWindowState.Normal
                    ? new Rectangle(form.Left, form.Top, form.Width, form.Height)
                    : form.RestoreBounds;
                if (b.Width >= 400 && b.Height >= 300)
                    File.WriteAllText(winFile, System.Text.Json.JsonSerializer.Serialize(
                        new { x = b.X, y = b.Y, w = b.Width, h = b.Height, max = state == FormWindowState.Maximized }));
            }
            catch { /* nicht speicherbar: naechster Start mit Standardgroesse */ }
            try { if (server is { HasExited: false }) server.Kill(entireProcessTree: true); }
            catch { /* Server war schon weg */ }
        };

        Application.Run(form);
    }

    private static string? _logoCache;

    private static string? LogoDataUrl()
    {
        if (_logoCache == null)
        {
            try
            {
                string basis = AppDomain.CurrentDomain.BaseDirectory;
                string[] kandidaten =
                {
                    Path.Combine(basis, "server", "_internal", "static", "logo.png"),  // Deployment
                    Path.Combine(basis, "..", "app", "static", "logo.png"),            // Entwicklung / paket
                };
                var pfad = kandidaten.FirstOrDefault(File.Exists);
                _logoCache = pfad != null
                    ? "data:image/png;base64," + Convert.ToBase64String(File.ReadAllBytes(pfad))
                    : "";
            }
            catch { _logoCache = ""; }
        }
        return _logoCache.Length > 0 ? _logoCache : null;
    }

    private static string LogoHtml(int groesse)
    {
        var url = LogoDataUrl();
        return url != null
            ? $"<img class=\"logo\" style=\"width:{groesse}px;height:{groesse}px\" src=\"{url}\" alt=\"\">"
            : $"<div class=\"logo emoji\" style=\"font-size:{Math.Max(24, groesse - 10)}px\">&#128196;</div>";
    }

    private static string SplashHtml() => """
        <!DOCTYPE html><html><head><meta charset="utf-8"><style>
        html,body{height:100%;margin:0}
        body{background:#17191d;color:#e6e9ee;font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center}
        .c{text-align:center}
        .logo{display:block;margin:0 auto 16px}
        .logo.emoji{line-height:1}
        h1{font-weight:600;margin:0 0 8px}
        p{color:#97a0af;margin:0}
        .bar{width:140px;height:3px;background:#2c313a;border-radius:2px;margin:18px auto 0;overflow:hidden}
        .bar i{display:block;width:40%;height:100%;background:#4cc2ff;border-radius:2px;animation:sl 1.1s infinite linear}
        @keyframes sl{from{transform:translateX(-100%)}to{transform:translateX(350%)}}
        </style></head><body><div class="c">__LOGO__<h1>FederPDF</h1><p>__START__</p><div class="bar"><i></i></div></body></html>
        """.Replace("__LOGO__", LogoHtml(84))
           .Replace("__START__", uiSprache == "en" ? "starting &hellip;" : "wird gestartet &hellip;");

    private static string ErrorHtml() => """
        <!DOCTYPE html><html><head><meta charset="utf-8"><style>
        html,body{height:100%;margin:0}
        body{background:#17191d;color:#e6e9ee;font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center}
        .c{text-align:center;max-width:420px}
        .logo{display:block;margin:0 auto 18px}
        .logo.emoji{line-height:1}
        h1{font-weight:600;margin:0 0 10px}
        p{color:#97a0af;line-height:1.6;margin:0}
        </style></head><body><div class="c">__LOGO__<h1>&#9888;&#65039; __ERRTITEL__</h1>
        <p>__ERRTEXT__</p></div></body></html>
        """.Replace("__LOGO__", LogoHtml(64))
           .Replace("__ERRTITEL__", uiSprache == "en" ? "Server not reachable" : "Server nicht erreichbar")
           .Replace("__ERRTEXT__", uiSprache == "en"
               ? "The FederPDF server could not be started.<br>Please close the program and start it again.<br>If the problem persists, check the <b>server</b> folder in the program directory."
               : "Der FederPDF-Server konnte nicht gestartet werden.<br>Bitte das Programm schlie\u00dfen und neu starten.<br>Besteht das Problem, den Ordner <b>server</b> im Programmverzeichnis <b>pr\u00fcfen</b>.");

    private static bool SaveCurrent()
    {
        try
        {
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
            var cur = http.GetStringAsync($"http://127.0.0.1:{port}/api/current").Result;
            using var doc = JsonDocument.Parse(cur);
            var id = doc.RootElement.GetProperty("id").GetString();
            if (string.IsNullOrEmpty(id)) return true; // nichts offen -> nichts zu speichern
            var resp = http.PostAsync($"http://127.0.0.1:{port}/api/save/{id}", null!).Result;
            dirty = false;
            return resp.IsSuccessStatusCode;
        }
        catch
        {
            return false;
        }
    }

    /// <summary>Echter Druck in DRUCKERAUFLOESUNG (Nutzer-Fund 22.10.2026,
    /// "Ausdruck komplett unscharf"): Der fruehere Weg druckte die HTML-Druck-
    /// ansicht mit 120-dpi-Bildschirm-Rastern ueber den WebView2-Druckdialog.
    /// Jetzt rendert der Server jede Seite (mit Annotationen/Formularwerten, im
    /// AKTUELLEN Stand) in Druckerqualitaet und dieses PrintDocument zeichnet
    /// sie einpassend aufs Papier. Vorschau + Einstellungen im eigenen
    /// DruckDialog (Nutzer: "keine Druckvorschau zu sehen"). Rueckkanal an die
    /// UI: pwDruckFertig(true|false|null).</summary>
    private static async Task DruckenAsync(string did, int aktuelleSeite, WebView2 webView)
    {
        try
        {
            int seiten;
            double[][] masse;
            using (var http = new HttpClient(new System.Net.Http.HttpClientHandler { UseProxy = false })
                   { Timeout = TimeSpan.FromSeconds(20) })
            {
                var json = await http.GetStringAsync($"http://127.0.0.1:{port}/api/druckinfo/{did}");
                using var doc = JsonDocument.Parse(json);
                seiten = doc.RootElement.GetProperty("pages").GetInt32();
                masse = doc.RootElement.GetProperty("groessen").EnumerateArray()
                    .Select(a => a.EnumerateArray().Select(v => v.GetDouble()).ToArray()).ToArray();
            }
            if (seiten <= 0 || masse.Length < seiten)
            {
                await Melden(webView, "null");
                return;
            }

            Image BildLader(int nr, int dpi, bool annots) => SeiteVomServer(did, nr, dpi, annots);
            var owner = webView.FindForm();
            using var dlg = new DruckDialog(seiten, aktuelleSeite, BildLader, uiSprache,
                owner?.DeviceDpi ?? 96, uiHell, masse, druckRandMm, druckOben, druckSw);
            if (owner != null) dlg.ZentrierenAuf(owner);   // im DPI-Kontext des Owners erstellen
            if (dlg.ShowDialog(owner) != DialogResult.OK)
            {
                await Melden(webView, "null");
                return;
            }
            string druckerName = dlg.GewaehlterDrucker;
            int kopien = dlg.Kopien;
            var liste = dlg.SeitenListe;
            var duplex = dlg.DuplexModus;
            bool mitAnnots = dlg.MitAnnots;
            double skalierung = dlg.Skalierung;
            int proBlatt = dlg.SeitenProBlatt;
            double randMm = dlg.RandMm;
            bool oben = dlg.ObenBuendig;
            bool farbe = dlg.Farbig;
            // Einstellungen inkl. Treiber-Eigenschaften (Papier/Qualitaet/Farbe
            // aus dem Druckereigenschaften-Dialog) MITNEHMEN, bevor der Dialog
            // disposed wird
            var druckerPs = dlg.DruckerEinstellungen;
            if (liste.Count == 0 || string.IsNullOrEmpty(druckerName))
            {
                await Melden(webView, "null");
                return;
            }
            // Seitenrand/Position/Farbwahl persistieren (Best-Effort, blockiert den Druck nicht)
            if (Math.Abs(randMm - druckRandMm) > 0.01 || oben != druckOben || farbe == druckSw)
            {
                druckRandMm = randMm;
                druckOben = oben;
                druckSw = !farbe;
                _ = Task.Run(PrefsRandSchreiben);
            }

            await Task.Run(() =>
            {
                var ps = druckerPs ?? new PrinterSettings { PrinterName = druckerName };
                ps.Copies = (short)Math.Max(1, Math.Min(kopien, 99));
                try { ps.Duplex = duplex; } catch { /* Treiber ohne Duplex: einseitig */ }
                double randPt = randMm * 72.0 / 25.4;   // Nutzer-Seitenrand mm -> pt
                // Render-DPI = Aufloesung des GEWAHLTEN Druckers (geklemmt: 600 dpi
                // ist Laserqualitaet, mehr waere nur Speicher). Erst HIER lesen - im
                // Hintergrund-Task: DefaultPageSettings fragt beim Offline-
                // Netzwerkdrucker Status ab und darf deshalb die UI blockieren.
                int dpi = 600;
                try
                {
                    var r = ps.DefaultPageSettings.PrinterResolution;
                    if (r != null && r.X > 0) dpi = Math.Clamp(r.X, 150, 600);
                }
                catch { }
                // PIXELBUDGET: Riesenseiten (Scans mit 2400 pt und mehr) wuerden
                // bei 600 dpi Gigabyte-Pixmapen bauen - im Server wie im Treiber-
                // Filter. Auf ~100 Mio px je Seite deckeln (A4 bei 600 dpi =
                // 35 Mio px bleibt unberuehrt; eine 2400-pt-Scanseite druckt dann
                // mit ~250 dpi - aufs Papier gleich gross, nur weicher).
                foreach (int nr in liste)
                {
                    double flaeche = masse[nr][0] * masse[nr][1];
                    if (flaeche <= 0) continue;
                    double maxDpi = Math.Sqrt(100e6 * 72.0 * 72.0 / flaeche);
                    if (dpi > maxDpi) dpi = Math.Max(150, (int)maxDpi);
                }

                using var druck = new PrintDocument { PrinterSettings = ps };
                druck.DefaultPageSettings.Margins = new Margins(0, 0, 0, 0);
                // Papierformat/Ausrichtung EXPLIZIT uebernehmen - der Druckdialog
                // schreibt sie in ps.DefaultPageSettings (Combos UND Treiber-
                // dialog); nicht auf Fallback-Plumbing von PrintDocument vertrauen
                try { druck.DefaultPageSettings.Landscape = ps.DefaultPageSettings.Landscape; } catch { }
                try { druck.DefaultPageSettings.PaperSize = ps.DefaultPageSettings.PaperSize; } catch { }
                // Farbmodus EXPLIZIT mitgeben (DMCOLOR): der Treiber entscheidet
                // sonst selbst - Nutzer-Fund "auf Farbe gestellt, Ausdruck blieb S/W"
                try { druck.DefaultPageSettings.Color = farbe; } catch { }
                int index = 0;
                druck.PrintPage += (_, ev) =>
                {
                    if (index >= liste.Count) { ev.HasMorePages = false; return; }
                    // EIN Blatt = bis zu proBlatt Auftragsseiten (N-up)
                    int bis = Math.Min(liste.Count, index + proBlatt);
                    var stapel = new List<(int nr, double bPt, double hPt)>();
                    for (int i = index; i < bis; i++)
                    {
                        int nr = liste[i];
                        stapel.Add((nr, masse[nr][0], masse[nr][1]));
                    }
                    index = bis;
                    using var http = new HttpClient(new System.Net.Http.HttpClientHandler { UseProxy = false })
                    { Timeout = TimeSpan.FromSeconds(120) };
                    // Seiten als PNG-Bytes holen (verlustfrei; S/W rendert der
                    // Server gleich in Graustufen, grau=1). BlattAusgeben
                    // reicht sie - wenn der Treiber mitspielt - unveraendert
                    // durch und dekodiert sonst selbst (Fallback).
                    var pngs = new List<byte[]>();
                    foreach (var (nr, _, _) in stapel)
                        pngs.Add(http.GetByteArrayAsync(
                            $"http://127.0.0.1:{port}/api/druckseite/{did}?nr={nr}&dpi={dpi}&annots={(mitAnnots ? 1 : 0)}&grau={(farbe ? 0 : 1)}").Result);
                    BlattAusgeben(ev.Graphics!, ev.PageSettings, stapel, pngs,
                        skalierung, proBlatt, randPt, oben, farbe);
                    ev.HasMorePages = index < liste.Count;
                };
                druck.Print();
            });
            await Melden(webView, "true");
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                (uiSprache == "en" ? "Printing failed:\n" : "Drucken fehlgeschlagen:\n") + ex.Message,
                "FederPDF", MessageBoxButtons.OK, MessageBoxIcon.Error);
            await Melden(webView, "false");
        }
    }

    /// <summary>Eine Druckseite vom Server holen (annots=false = pures Papier
    /// ohne Signaturen/Markierungen/Formulare). Zurueck kommt eine KOPIE als
    /// eigenstaendiges Bitmap: GDI+ liest Image.FromStream traege aus dem
    /// Stream - der lokale MemoryStream waere per GC einholbar und der Puffer
    /// beim naechsten Malvorgang weg -> AccessViolation, App-Absturz
    /// (Nutzer-Fund 22.10.: "kurz Vorschau gesehen, dann beendet").</summary>
    private static Image SeiteVomServer(string did, int nr, int dpi, bool annots)
    {
        using var http = new HttpClient(new System.Net.Http.HttpClientHandler { UseProxy = false })
        { Timeout = TimeSpan.FromSeconds(30) };
        // fmt=jpg: das 600-dpi-PNG waere 25-50 MB gross und langsam zu dekodieren —
        // JPEG zieht den Druckstart spuerbar vor (Nutzer-Fund), bei Druckaufloesung
        // visuell nicht unterscheidbar
        using var antwort = http.GetStreamAsync(
            $"http://127.0.0.1:{port}/api/druckseite/{did}?nr={nr}&dpi={dpi}&annots={(annots ? 1 : 0)}&fmt=jpg&q=85").Result;
        using var ms = new MemoryStream();
        antwort.CopyTo(ms);
        ms.Position = 0;
        using var roh = System.Drawing.Image.FromStream(ms);
        return new Bitmap(roh);
    }

    private static async Task Melden(WebView2 webView, string wert)
    {
        try { await webView.CoreWebView2.ExecuteScriptAsync($"window.pwDruckFertig && window.pwDruckFertig({wert});"); }
        catch { /* UI evtl. schon geschlossen */ }
    }

    /// <summary>Seitenrand + Position in die UI-Praeferenzen schreiben:
    /// GET /api/prefs, Schluessel "druckRandMm"/"druckOben" setzen, POST
    /// zurueck — der Server bleibt alleiniger Schreiber der einstellungen.json.
    /// Best-Effort: scheitert es (Server weg, kaputtes JSON), bleibt es beim
    /// alten Stand.</summary>
    private static void PrefsRandSchreiben()
    {
        try
        {
            using var http = new HttpClient(new System.Net.Http.HttpClientHandler { UseProxy = false })
            { Timeout = TimeSpan.FromSeconds(5) };
            var json = http.GetStringAsync($"http://127.0.0.1:{port}/api/prefs").Result;
            var node = System.Text.Json.Nodes.JsonNode.Parse(json) as System.Text.Json.Nodes.JsonObject;
            if (node == null) return;
            node["druckRandMm"] = druckRandMm;
            node["druckOben"] = druckOben;
            node["druckSw"] = druckSw;
            using var content = new StringContent(node.ToJsonString(),
                System.Text.Encoding.UTF8, "application/json");
            http.PostAsync($"http://127.0.0.1:{port}/api/prefs", content).Wait();
        }
        catch { /* Prefs sind Best-Effort - der Druck ist davon unberuehrt */ }
    }

    /// <summary>Seitenbild in Graustufen rechnen (Luminanz, Rec.601) — für die
    /// S/W-Farbwahl in Vorschau UND Druck (Vorschau = Druck).</summary>
    internal static Bitmap Graustufen(Image quelle)
    {
        var grau = new Bitmap(quelle.Width, quelle.Height);
        using (var g = Graphics.FromImage(grau))
        {
            var m = new System.Drawing.Imaging.ColorMatrix
            {
                Matrix00 = 0.299f, Matrix01 = 0.299f, Matrix02 = 0.299f,
                Matrix10 = 0.587f, Matrix11 = 0.587f, Matrix12 = 0.587f,
                Matrix20 = 0.114f, Matrix21 = 0.114f, Matrix22 = 0.114f,
                Matrix33 = 1f, Matrix44 = 1f,
            };
            using var ia = new System.Drawing.Imaging.ImageAttributes();
            ia.SetColorMatrix(m);
            g.DrawImage(quelle, new Rectangle(0, 0, quelle.Width, quelle.Height),
                        0, 0, quelle.Width, quelle.Height, GraphicsUnit.Pixel, ia);
        }
        return grau;
    }

    /// <summary>Seitenbild in horizontale STREIFEN zu je ~2,5 Zoll teilen und
    /// zeichnen (ziel in 1/100 Zoll): EINE riesige Stretch-Blt-Operation
    /// (A4 bei 600 dpi ≈ 7000×4900 px) rastern manche Treiber am letzten
    /// Band-Streifen als Balken/Farbverläufe — der unterste Zentimeter des
    /// Ausdrucks war unlesbar (Nutzer-Fund am Fahrzeugschein). Die Streifen
    /// sind quellgetreu zugeordnet, das Ergebnis identisch zum einen Blt.
    /// Screen-Zeichnung (Vorschau) braucht das nicht.</summary>
    private static void BildGebandertZeichnen(Graphics g, Image bild, RectangleF ziel)
    {
        float dpy = Math.Max(50f, g.DpiY);
        double bandH = 25000.0 / dpy;   // 1/100 Zoll (~250 Geraetepixel)
        if (ziel.Height <= bandH)
        {
            g.DrawImage(bild, ziel);
            return;
        }
        for (double y = 0; y < ziel.Height - 0.01;)
        {
            double dH = Math.Min(bandH, ziel.Height - y);
            var z = new RectangleF(ziel.X, ziel.Y + (float)y, ziel.Width, (float)dH);
            var q = new RectangleF(0, (float)(bild.Height * y / ziel.Height),
                                   bild.Width, (float)(bild.Height * dH / ziel.Height));
            g.DrawImage(bild, z, q, GraphicsUnit.Pixel);
            y += dH;
        }
    }

    /// <summary>Eine PDF-Seite zeichnen: Seitenverhaeltnis erhalten, zentriert
    /// in der druckbaren Flaeche, nie ueber Hardware-Raender hinaus.
    /// skalierung 0 = an Seitenrand anpassen (NUR skalieren - seit v0.21.41
    /// KEINE automatische 90-Grad-Drehung mehr, Nutzer-Fund "Fahrzeugschein
    /// wird um 90 Grad gedreht": Seiten drucken so, wie sie angezeigt werden;
    /// das Blattformat steuert die Ausrichtungs-Combo); jeder andere Wert =
    /// fester Faktor (1,0 = tatsaechliche Groesse) - Ueberhaenge clippt der
    /// Treiber wie bei Acrobat. Koordinaten in 1/100 Zoll - GraphicsUnit.
    /// Display ist beim Drucker genau das. Die Flaeche kommt orientierungs-
    /// korrigiert aus DruckLayout (PrintableArea folgt der Landscape-DEVMODE
    /// nicht, Mess-Fund 31.10.2026).</summary>
    private static void SeiteEinpassen(Graphics g, PageSettings seite, Image bild,
                                       double bPt, double hPt, double skalierung = 0,
                                       double randPt = 0, bool oben = false)
    {
        g.PageUnit = GraphicsUnit.Display;
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.SmoothingMode = SmoothingMode.HighQuality;
        var ziel = Zielrechtecke(seite, new List<(int, double, double)> { (0, bPt, hPt) },
                                 skalierung, 1, randPt, oben)[0];
        BildGebandertZeichnen(g, bild, ziel);
    }

    /// <summary>Druckbare Flaeche in pt, GDI-Ursprung genullt (OriginAtMargins=
    /// false, Doku: der Ursprung liegt bereits an der Ecke der druckbaren
    /// Flaeche - X/Y gehoeren NICHT in die Zeichnung) und um den Nutzer-Rand
    /// eingezogen. REIHENFOLGE: erst Ursprung nullen, DANN den Rand (sonst
    /// verliert der Inset seine Position).</summary>
    private static RectangleF DruckbarMitRand(PageSettings seite, double randPt)
    {
        var druckbar = DruckLayout.DruckbareFlaeche(seite, seite.Bounds.Width * 0.72, seite.Bounds.Height * 0.72);
        druckbar.X = 0f;
        druckbar.Y = 0f;
        if (randPt > 0)
        {
            druckbar = RectangleF.Inflate(druckbar, -(float)randPt, -(float)randPt);
            if (druckbar.Width < 1f || druckbar.Height < 1f)
                druckbar = new RectangleF(druckbar.X, druckbar.Y, 1f, 1f);
        }
        return druckbar;
    }

    /// <summary>Zielrechtecke (1/100 Zoll) je Stapelseite - die GEMEINSAME
    /// Geometrie fuer Bitmap-Zeichnung (BlattZeichnen) und PNG-Durchreichen
    /// (BlattZeichnenPng): 1-up einpassend (feste Skalierung falls gewaehlt,
    /// kopfbuendig auf Wunsch), N-up ins DruckLayout-Gitter.</summary>
    internal static List<RectangleF> Zielrechtecke(PageSettings seite,
        List<(int nr, double bPt, double hPt)> stapel, double skalierung, int proBlatt,
        double randPt, bool oben)
    {
        var ergebnis = new List<RectangleF>();
        if (proBlatt <= 1)
        {
            var (_, bPt, hPt) = stapel[0];
            var druckbar = DruckbarMitRand(seite, randPt);          // pt
            // ACHTUNG: nach dem Rand-Einziehen (Inflate negativ) liegt
            // druckbar.X/Y beim Rand, nicht bei 0 - das Offset gehoert MIT
            // in die Zielposition (Refaktor-Falle: ohne ax/ay wandert das
            // Bild bei Nutzer-Rand an den Hardware-Rand)
            float ax = druckbar.X / 0.72f, ay = druckbar.Y / 0.72f;
            float aw = Math.Max(1f, druckbar.Width / 0.72f), ah = Math.Max(1f, druckbar.Height / 0.72f);
            double b100 = bPt / 72.0 * 100.0, h100 = hPt / 72.0 * 100.0;   // Seite in 1/100 Zoll
            double skala = skalierung <= 0 ? Math.Min(aw / b100, ah / h100) : skalierung;
            double b = b100 * skala, h = h100 * skala;
            ergebnis.Add(new RectangleF(
                ax + (float)((aw - b) / 2.0),
                ay + (float)(oben ? 0 : (ah - h) / 2.0),   // kopfbuendig auf Wunsch
                (float)b, (float)h));
            return ergebnis;
        }
        var flaeche = DruckbarMitRand(seite, randPt);
        var (spalten, zeilen) = DruckLayout.Gitter(stapel.Count, flaeche.Width, flaeche.Height,
                                                   stapel[0].bPt, stapel[0].hPt);
        for (int i = 0; i < stapel.Count; i++)
        {
            var zelle = DruckLayout.Zelle(flaeche, spalten, zeilen, i);
            var ziel = DruckLayout.SeiteInZelle(stapel[i].bPt, stapel[i].hPt, zelle, 0, oben);
            ergebnis.Add(new RectangleF(ziel.X / 0.72f, ziel.Y / 0.72f, ziel.Width / 0.72f, ziel.Height / 0.72f));
        }
        return ergebnis;
    }

    /// <summary>Einen Druck-Blattbogen zeichnen (Koordinaten 1/100 Zoll):
    /// 1 Seite pro Blatt nutzt den bewaehrten SeiteEinpass-Pfad (mit fester
    /// Skalierung, falls gewaehlt); mehrere Seiten werden als N-up-Gitter
    /// (DruckLayout) komponiert - jede Zelle einpassend, OHNE automatische
    /// Drehung (v0.21.41), identisch zur Vorschau ("Vorschau = Druck").
    /// randPt = Nutzer-Seitenrand (mm in pt), allseitig INNERHALB der
    /// druckbaren Flaeche einziehen - Einpassen/Zentrieren rechnet mit der
    /// schmaleren Flaeche (symmetrischer Rahmen). Internal fuer den kopflosen
    /// Druck-Harness. Das ist der BITMAP-Fallback (siehe BlattAusgeben).</summary>
    internal static void BlattZeichnen(Graphics g, PageSettings seite,
        List<(int nr, double bPt, double hPt)> stapel, List<Image> bilder,
        double skalierung, int proBlatt, double randPt = 0, bool oben = false)
    {
        if (stapel.Count == 0 || stapel.Count > bilder.Count) return;
        g.PageUnit = GraphicsUnit.Display;
        g.InterpolationMode = InterpolationMode.HighQualityBicubic;
        g.SmoothingMode = SmoothingMode.HighQuality;
        var ziele = Zielrechtecke(seite, stapel, skalierung, proBlatt, randPt, oben);
        for (int i = 0; i < stapel.Count; i++)
            BildGebandertZeichnen(g, bilder[i], ziele[i]);
    }

    // --- PNG-Durchreichen (GDI-Passthrough): das komprimierte Seitenbild geht
    // UNVERAENDERT an den Treiber (StretchDIBits mit BI_PNG), statt als
    // dekodierte Bitmap, die der GDI->XPS-Konverter (MXDC) in ~2-MB-Baender
    // zerlegt und FARBIGE Baender als JPEG-KACHELN kodiert. Genau die kippen
    // beim Rastern in den Druckerstrom (Nutzer-Fund 10.11.2026, Gothaer-
    // Beitragsrechnung am HP 9010/IPP-Klassentreiber: oberes Drittel mit um
    // 5,3 mm versetzten Baendern und schwarzen Querlinien in exakt der Breite
    // des Seitenbilds - Stossgrenzen kartenweise auf den JPEG-Kachelgrenzen,
    // verlustfreie Baender kamen immer korrekt; dasselbe Bild wie beim
    // Fahrzeugschein-Fund "unterster Zentimeter unlesbar"). Ohne JPEG-Kacheln
    // gibt es nichts zu vertauschen - und der Ausdruck verliert die JPEG-
    // Artefakte dazu. Klassische GDI-Treiber ohne CHECKPNGFORMAT nutzen den
    // Bitmap-Fallback (BlattZeichnen), der bleibt scharf geschaltet.
    private const int QUERYESCSUPPORT = 8, CHECKPNGFORMAT = 4120, BI_PNG = 5;
    private const uint SRCCOPY = 0x00CC0020;

    [StructLayout(LayoutKind.Sequential)]
    private struct BITMAPINFOHEADER
    {
        public int biSize, biWidth, biHeight;
        public short biPlanes, biBitCount;
        public int biCompression, biSizeImage, biXPelsPerMeter, biYPelsPerMeter, biClrUsed, biClrImportant;
    }

    [DllImport("gdi32.dll")]
    private static extern int ExtEscape(IntPtr hdc, int nEscape, int cbInput, ref int lpszInData, int cbOutput, IntPtr lpszOutData);
    [DllImport("gdi32.dll")]
    private static extern int ExtEscape(IntPtr hdc, int nEscape, int cbInput, byte[] lpszInData, int cbOutput, out int lpszOutData);
    [DllImport("gdi32.dll", SetLastError = true)]
    private static extern int StretchDIBits(IntPtr hdc, int xDest, int yDest, int wDest, int hDest,
        int xSrc, int ySrc, int wSrc, int hSrc, byte[] bits, ref BITMAPINFOHEADER bmi, uint usage, uint rop);

    /// <summary>Pixelmasse aus dem PNG-IHDR lesen (kein Dekodieren noetig).</summary>
    private static (int breite, int hoehe) PngMasse(byte[] png)
    {
        if (png.Length >= 24 && png[12] == (byte)'I' && png[13] == (byte)'H')
            return ((png[16] << 24) | (png[17] << 16) | (png[18] << 8) | png[19],
                    (png[20] << 24) | (png[21] << 16) | (png[22] << 8) | png[23]);
        return (0, 0);
    }

    /// <summary>Kann dieser Drucker das PNG unvermittelt uebernehmen?
    /// (v4/XPS-Drucker via MXDC: ja; klassische GDI-Treiber: nein)</summary>
    private static bool PngDurchreichenMoeglich(IntPtr hdc, byte[] png)
    {
        try
        {
            int esc = CHECKPNGFORMAT;
            int ok = -1;
            return ExtEscape(hdc, QUERYESCSUPPORT, sizeof(int), ref esc, 0, IntPtr.Zero) > 0
                && ExtEscape(hdc, CHECKPNGFORMAT, png.Length, png, sizeof(int), out ok) > 0 && ok == 1;
        }
        catch { return false; }
    }

    /// <summary>Seitenbild als PNG direkt an den Drucker-DC (ziel in 1/100 Zoll,
    /// dpi = Geraeteaufloesung des Graphics). false = abgelehnt/fehlgeschlagen.</summary>
    private static bool PngBlit(IntPtr hdc, byte[] png, RectangleF ziel, float dpiX, float dpiY)
    {
        var (breite, hoehe) = PngMasse(png);
        if (breite <= 0 || hoehe <= 0) return false;
        var bmi = new BITMAPINFOHEADER
        {
            biSize = Marshal.SizeOf<BITMAPINFOHEADER>(),
            biWidth = breite,
            biHeight = -hoehe,                // top-down
            biPlanes = 1,
            biBitCount = 0,
            biCompression = BI_PNG,
            biSizeImage = png.Length,
        };
        int z = StretchDIBits(hdc,
            (int)Math.Round(ziel.X * dpiX / 100.0), (int)Math.Round(ziel.Y * dpiY / 100.0),
            (int)Math.Round(ziel.Width * dpiX / 100.0), (int)Math.Round(ziel.Height * dpiY / 100.0),
            0, 0, breite, hoehe, png, ref bmi, 0, SRCCOPY);
        return z == hoehe;                    // Erfolg = Anzahl kopierter Scanlines
    }

    /// <summary>Blatt wie BlattZeichnen, aber die Seitenbilder werden als PNG
    /// durchgereicht (kein Dekodieren, keine JPEG-Kacheln im Spool). Pruefung
    /// und alle Blits in EINEM GetHdc-Zyklus - Graphics duldet keine zweite
    /// HDC-Entleihung, solange die erste abgeschlossen ist (InvalidOperationException
    /// "Object is currently in use elsewhere", Fund am HP-IPP-Klassentreiber).</summary>
    private static bool BlattZeichnenPng(Graphics g, PageSettings seite,
        List<(int nr, double bPt, double hPt)> stapel, List<byte[]> pngs,
        double skalierung, int proBlatt, double randPt, bool oben)
    {
        if (stapel.Count == 0 || stapel.Count > pngs.Count) return false;
        g.PageUnit = GraphicsUnit.Display;
        g.ResetTransform();                       // DC in den Urzustand, Pixel sind Pixel
        // dpiX/dpiY VOR GetHdc lesen: zwischen GetHdc und ReleaseHdc darf keine
        // Graphics-Methode angeruehrt werden (InvalidOperationException)
        float dpiX = g.DpiX, dpiY = g.DpiY;
        var ziele = Zielrechtecke(seite, stapel, skalierung, proBlatt, randPt, oben);
        IntPtr hdc = g.GetHdc();
        try
        {
            if (!PngDurchreichenMoeglich(hdc, pngs[0])) return false;
            for (int i = 0; i < stapel.Count; i++)
                if (!PngBlit(hdc, pngs[i], ziele[i], dpiX, dpiY)) return false;
            return true;
        }
        catch { return false; }
        finally { g.ReleaseHdc(hdc); }
    }

    /// <summary>Eine Blattseite ausgeben: PNG durchreichen, wenn der Treiber
    /// das kann (je Blatt geprueft - CHECKPNGFORMAT ist ein billiger Escape),
    /// sonst dekodieren und als Bitmap zeichnen. Internal fuer den kopflosen
    /// Druck-Harness - der prueft genau diesen Weg E2E.</summary>
    internal static void BlattAusgeben(Graphics g, PageSettings seite,
        List<(int nr, double bPt, double hPt)> stapel, List<byte[]> pngs,
        double skalierung, int proBlatt, double randPt, bool oben, bool farbe)
    {
        if (stapel.Count == 0 || stapel.Count > pngs.Count) return;
        if (BlattZeichnenPng(g, seite, stapel, pngs, skalierung, proBlatt, randPt, oben)) return;
        var bilder = new List<Image>();
        try
        {
            foreach (var png in pngs)
            {
                // KOPIE als eigenstaendiges Bitmap: GDI+ liest Image.FromStream
                // traege aus dem Stream - der lokale MemoryStream waere per GC
                // einholbar und der Puffer beim Malvorgang weg -> AccessViolation
                using var ms = new MemoryStream(png);
                using var roh = System.Drawing.Image.FromStream(ms);
                var b = new Bitmap(roh);
                // S/W: der Server liefert bereits grau (grau=1); gegen einen
                // aelteren Server (der das noch nicht kennt) faerben wir selbst
                if (!farbe && roh.PixelFormat != System.Drawing.Imaging.PixelFormat.Format8bppIndexed)
                {
                    var grau = Graustufen(b);
                    b.Dispose();
                    b = grau;
                }
                bilder.Add(b);
            }
            BlattZeichnen(g, seite, stapel, bilder, skalierung, proBlatt, randPt, oben);
        }
        finally { foreach (var b in bilder) b.Dispose(); }
    }

    private static int GetFreePort()
    {
        var listener = System.Net.Sockets.TcpListener.Create(0);
        listener.Start();
        int port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        return port;
    }

    /// <summary>WebView2 manuell auf die Clientflaeche abzueglich Rahmen setzen.
    /// Umgeht den DPI-Skalier-Bug beim Wiederherstellen aus fenster.json, bei dem
    /// das Dock-Fill-Control in CSS- statt physischer Groesse landet (Klick-De-Sync).</summary>
    private static void WebViewAufInnenflaecheSetzen(Form form, WebView2 webView)
    {
        var p = form.Padding;
        webView.Bounds = new Rectangle(p.Left, p.Top,
            form.ClientSize.Width - p.Horizontal,
            form.ClientSize.Height - p.Vertical);
    }
}

/// <summary>Rahmenloses Hauptfenster: die App-Kopfzeile ist die Titelleiste,
/// die 6px-Raender links/rechts/unten sind Groesse-Anfasspunkte.</summary>
internal sealed class HauptForm : Form
{
    private const int WM_NCHITTEST = 0x84;
    private const int HTLEFT = 10, HTRIGHT = 11, HTTOP = 12, HTTOPLEFT = 13, HTTOPRIGHT = 14,
                      HTBOTTOM = 15, HTBOTTOMLEFT = 16, HTBOTTOMRIGHT = 17;
    private const int WM_NCLBUTTONDOWN = 0xA1;
    private const int HTCAPTION = 2;
    private const int WM_DPICHANGED = 0x02E0;
    private const int WM_GETDPISCALEDSIZE = 0x02E4;

    [StructLayout(LayoutKind.Sequential)]
    private struct VorschlagsRect
    {
        public int Links, Oben, Rechts, Unten;
    }

    // lParam von WM_GETDPISCALEDSIZE ist eine SIZE-Struktur (Breite/Hoehe),
    // KEIN Rect - ein Rect-Zugriff liefert Muell und das System faellt dann
    // auf unskaliert zurueck (Diagnose 11.10.2026)
    [StructLayout(LayoutKind.Sequential)]
    private struct SkalierteGroesse
    {
        public int Breite, Hoehe;
    }

    [DllImport("user32.dll")]
    private static extern bool ReleaseCapture();

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hWnd, int msg, int wParam, int lParam);

    // Eckenrundung wie bei Win11-Programmen ueblich (Nutzer-Wunsch v0.21.9):
    // DWMWA_WINDOW_CORNER_PREFERENCE = 33; DWMWCP_ROUND = 2, DONOTROUND = 1.
    // Der DWM rundet damit auch rahmenlose Fenster (unser FormBorderStyle.None)
    // und schneidet den Fensterinhalt an der Rundung; Schatten liefert das
    // System mit. Win10 kennt das Attribut nicht - der Aufruf scheitert mit
    // Fehlercode und das Fenster bleibt eckig (dort Standard).
    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribut, ref int wert, int groesse);

    private const int DwmwaBorderColor = 34;
    private const int DwmwaColorNone = unchecked((int)0xFFFFFFFE);   // keine Haarlinie

    // Der DWM-Standardbogen (~8 px logisch) ist kaum erkennbar (Nutzer-Runde 2,
    // 13.10.2026): das Fenster schneidet sich deshalb SELBST mit einem groesseren
    // gerundeten Radius. Eine Region ist hartkantig (kein Antialiasing), aber bei
    // 14 px logisch hochskaliert sauber; der Schatten bleibt vom System.
    [DllImport("gdi32.dll")]
    private static extern IntPtr CreateRoundRectRgn(int links, int oben, int rechts, int unten, int bogenBreite, int bogenHoehe);

    [DllImport("user32.dll")]
    private static extern int SetWindowRgn(IntPtr hwnd, IntPtr region, bool neuZeichnen);

    private int eckenAktuell = -1;   // zuletzt gesetzter DWM-Wert (Skip von Doppel-Setzungen)

    /// <summary>Eckenradius in physischen Pixeln: 14 px logisch - deutlich
    /// erkennbar runder als der Win11-Standardbogen (~8 px), ohne Kasper-Figur.</summary>
    private int EckenRadiusPx() => Math.Max(10, (int)Math.Round(14.0 * DeviceDpi / 96.0));

    /// <summary>Eckenrundung je Fensterzustand: normal gerundet (DWM-Schatten +
    /// eigene, groessere Region), maximiert NICHT — das System quadriert
    /// maximierte Fenster normalerweise selbst, wir verlassen uns aber nicht
    /// darauf. Läuft über RandAnwenden mit, weil jeder Zustandswechsel dort
    /// vorbeikommt; der DWM-Wert wird gemerkt, die Region setzt pro Größe neu.
    /// Die DWM-Haarlinie (BORDER_COLOR) nehmen wir NUR: sie folgt dem kleineren
    /// 8px-Bogen und würde sonst sichtbar durch die eigene Ecke laufen.</summary>
    private void EckenAnwenden()
    {
        if (!IsHandleCreated) return;
        try
        {
            if (WindowState == FormWindowState.Maximized)
            {
                SetzeDwmEcke(1);   // DONOTROUND
                _ = SetWindowRgn(Handle, IntPtr.Zero, false);   // Region lösen: eckig bis zum Rand
                return;
            }
            SetzeDwmEcke(2);      // ROUND: der System-Schatten bleibt
            int r = EckenRadiusPx();
            IntPtr region = CreateRoundRectRgn(0, 0, Width + 1, Height + 1, r, r);
            _ = SetWindowRgn(Handle, region, false);   // System übernimmt die Region
        }
        catch { }   // Win10/alt: eckig lassen, nie zum Startproblem machen
    }

    private void SetzeDwmEcke(int wert)
    {
        if (wert == eckenAktuell) return;
        try
        {
            _ = DwmSetWindowAttribute(Handle, 33, ref wert, sizeof(int));
            int keine = DwmwaColorNone;   // Haarlinie ab: folgt dem 8px-Bogen, nicht unserer Region
            _ = DwmSetWindowAttribute(Handle, DwmwaBorderColor, ref keine, sizeof(int));
            eckenAktuell = wert;
        }
        catch { eckenAktuell = wert; }
    }

    /// <summary>Ziehen der Kopfzeile an das System uebergeben (inkl. Snap an Bildschirmraender).</summary>
    public void Titelziehen()
    {
        ReleaseCapture();
        _ = SendMessage(Handle, WM_NCLBUTTONDOWN, HTCAPTION, 0);
    }

    /// <summary>Maximieren/Wiederherstellen mit taskbar-sicherer Flaeche.</summary>
    public void MaximierenWechseln()
    {
        MaximizedBounds = Screen.FromControl(this).WorkingArea;
        WindowState = WindowState == FormWindowState.Maximized
            ? FormWindowState.Normal
            : FormWindowState.Maximized;
    }

    // Markenfarben wie das Band ueber der Kopfzeile (index.html header::before)
    private static readonly Color RandSchwarz = Color.FromArgb(26, 26, 26);
    private static readonly Color RandRot = Color.FromArgb(221, 0, 0);
    private static readonly Color RandGold = Color.FromArgb(255, 204, 0);

    // Innerer Ziehzone-Ring in der Farbe des ANGRENZENDEN UI (v0.21.4):
    // Viewer-Hintergrund - dunkel wie hell nahezu unsichtbar
    private static readonly Color InnenDunkel = Color.FromArgb(23, 25, 29);      // #17191d
    private static readonly Color InnenHell = Color.FromArgb(238, 241, 245);     // #eef1f5

    private static bool licht;

    public void ThemeSetzen(bool hell)
    {
        licht = hell;
        if (IsHandleCreated) Invalidate();
    }

    // Ziehzone in PHYSISCHEN Pixeln, an native Rahmen angelehnt (8 px bei
    // 100 %, 12 px bei 150 %) - die v0.18.11er 4 px waren halb so breit wie
    // bei jedem anderen Programm (Nutzer: "Ecke schwer zu treffen").
    // Seit der v0.21.9-Ergaenzung gilt sie NUR noch im WM_NCHITTEST (Greif-
    // breite); das Layout-Inset (Padding) ist der sichtbare BandPx-Streifen,
    // sonst liegt zwischen Schliessen-Knopf und Fensterrand ein toter Streifen
    // (Nutzer-Foto 13.10.2026).
    private int ZiehzonePx() => Math.Max(8, (int)Math.Round(8.0 * DeviceDpi / 96.0));

    /// <summary>Ober-Greifzone in physischen Pixeln, absichtlich SCHMALER als
    /// die Seiten-Zonen: die Kopfzeile ist die Ziehflaeche zum Verschieben,
    /// nur ihr oberster Streifen wird Griffrand (v0.21.34 - vorher war die
    /// Oberkante gar nicht greifbar, die Ecken oben nur in der Breite).
    /// Seit v0.21.36 ist Padding.Top GENAU diese Zone: NCHITTEST ueber dem
    /// WebView greift nicht (Maus geht ans Kindfenster), deshalb gehoeren
    /// die Kanten-Pixel dem Fenster selbst.</summary>
    private int ObengriffPx() => Math.Max(4, (int)Math.Round(6.0 * DeviceDpi / 96.0));

    // Sichtbares Band in physischen Pixeln: der Trikolore-Streifen (4 px,
    // Nutzer-Wunsch v0.18.11). Das WebView2 reicht bis direkt dahinter.
    private const int BandPx = 4;

    /// <summary>Band (Padding) je Fensterzustand setzen: maximiert randlos,
    /// sonst der schmale sichtbare Streifen an SEITEN/UNTEN und OBEN der
    /// OBERGRIFF (v0.21.36): Eigenpixels fuer die Kante - NCHITTEST-Zonen
    /// ueber dem WebView greifen NICHT (die Maus geht ans Kindfenster), die
    /// Oberkante war deshalb trotz HTTOP nicht zu fassen (Nutzer-Fund; der
    /// kopflose Harness ohne WebView sah den Fehler nicht). Der Streifen
    /// wird im Fensterton gemalt, das Trikolore-Band der Kopfzeile bleibt
    /// unveraendert sichtbar.</summary>
    public void RandAnwenden()
    {
        EckenAnwenden();   // Eckenrundung mit dem Zustand mitziehen (normal gerundet, maximiert eckig)
        Padding = WindowState == FormWindowState.Maximized
            ? Padding.Empty
            : new Padding(BandPx, ObengriffPx(), BandPx, BandPx);
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);
        EckenAnwenden();   // Handle(-neu)aufbau: Attribut ist fenstergebunden, wieder setzen
    }

    /// <summary>Native Größenänderung an der Ecke unten rechts starten (der
    /// HTML-Greifgriff in der Fußleiste löst sie per "fenster|groesse" aus;
    /// der modale Systemzug übernimmt den bereits gehaltenen Mauszeiger).</summary>
    public void GroesseZiehen()
    {
        ReleaseCapture();
        _ = SendMessage(Handle, WM_NCLBUTTONDOWN, HTBOTTOMRIGHT, 0);
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        var g = e.Graphics;
        int zone = Padding.Left;      // Band an den Seiten/unten
        int oben = Padding.Top;       // OBERGRIFF (v0.21.36): Eigenpixels oben
        if (zone == 0 && oben == 0) return;   // maximiert: kein Rand
        // Der duenne Trikolore-Streifen (4 px, Nutzer-Wunsch v0.18.11) an
        // LINKS/RECHTS/UNTEN - oben liefert die Kopfzeile ihren eigenen
        // CSS-Streifen. Die breite Greifzone liegt unsichtbar im WM_NCHITTEST
        // ueber dem WebView-Rand und wird nicht gemalt.
        int sichtbar = Math.Min(4, zone);
        using (var bi = new SolidBrush(licht ? InnenHell : InnenDunkel))
        {
            g.FillRectangle(bi, 0, 0, zone, Height);                       // links
            g.FillRectangle(bi, Width - zone, 0, zone, Height);            // rechts
            g.FillRectangle(bi, 0, Height - zone, Width, zone);            // unten
            // OBER-STREIFEN (v0.21.36): im Fensterton - macht die Kante zu
            // Eigenpixels des Fensters (NCHITTEST ueber dem WebView greift
            // nicht, die Maus geht ans Kindfenster)
            g.FillRectangle(bi, 0, 0, Width, oben);                        // oben
        }
        // Trikolore-KAMM an der GANZ OBERSTEN Kante (v0.21.37): das CSS-Band
        // der Kopfzeile entfiel (das WebView beginnt erst unterm Griffrand,
        // ein Band dort erschiene eingelassen und die Ecke schlösse nicht
        // bündig, Nutzer-Fund) - der Wrapper malt das Band jetzt selbst in
        // voller Fensterbreite, die Seitenbaender reichen bis y=0 und
        // schliessen nahtlos an. Hoehe 3px logisch wie das alte CSS-Band.
        int kanteH = Math.Max(3, (int)Math.Ceiling(3.0 * DeviceDpi / 96.0));
        var kamm0 = new ColorBlend
        {
            Positions = new float[] { 0f, 0.5f, 1f },
            Colors = new[] { RandSchwarz, RandRot, RandGold }
        };
        using (var pk = new LinearGradientBrush(new Rectangle(0, 0, Width, kanteH), RandSchwarz, RandGold, LinearGradientMode.Horizontal))
        { pk.InterpolationColors = kamm0; g.FillRectangle(pk, 0, 0, Width, kanteH); }
        // Verlaufskamm schwarz - rot - gold wie das CSS-Band (50% Rot). Der
        // Umlauf beginnt/endet an den oberen Ecken mit denselben Farben wie
        // der CSS-Streifen (links schwarz, rechts gold) - nahtloser Ansatz.
        var kamm = new ColorBlend
        {
            Positions = new float[] { 0f, 0.5f, 1f },
            Colors = new[] { RandSchwarz, RandRot, RandGold }
        };
        var kammUmgekehrt = new ColorBlend
        {
            Positions = new float[] { 0f, 0.5f, 1f },
            Colors = new[] { RandGold, RandRot, RandSchwarz }
        };
        using (var pr = new LinearGradientBrush(new Rectangle(Width - sichtbar, 0, sichtbar, Height), RandGold, RandSchwarz, LinearGradientMode.Vertical))
        { pr.InterpolationColors = kammUmgekehrt; g.FillRectangle(pr, Width - sichtbar, 0, sichtbar, Height); }
        using (var pu = new LinearGradientBrush(new Rectangle(0, Height - sichtbar, Width, sichtbar), RandGold, RandSchwarz, LinearGradientMode.Horizontal))
        { pu.InterpolationColors = kammUmgekehrt; g.FillRectangle(pu, 0, Height - sichtbar, Width, sichtbar); }
        using (var pl = new LinearGradientBrush(new Rectangle(0, 0, sichtbar, Height), RandSchwarz, RandGold, LinearGradientMode.Vertical))
        { pl.InterpolationColors = kamm; g.FillRectangle(pl, 0, 0, sichtbar, Height); }
    }

    protected override void OnResize(EventArgs e)
    {
        RandAnwenden();   // Ziehzone VOR dem Layout (DPI-abhaengig; maximiert randlos)
        base.OnResize(e);
        // Groessenaenderung: Verlaufsrand STRECKENWEISE komplett neu zeichnen -
        // Windows malt sonst nur die freigelegten Streifen, an den Grenzflaechen
        // zum WebView2 bleiben weisse Reststriche stehen. Zweites Invalidate
        // NACH dem Layout (falls das WebView2 den Rand zwischenzeitlich
        // uebermalt hat) - nur mit fertigen Fensterhandle, sonst wuerfe
        // BeginInvoke beim Start (fenster.json-Restore) die App wegwerfen.
        Invalidate();
        if (IsHandleCreated)
        {
            try { BeginInvoke((Action)(() => Invalidate())); } catch { }
        }
    }

    protected override void OnLoad(EventArgs e)
    {
        DoubleBuffered = true;   // randloses Fenster: Verlaufsrand ohne Flackern
        MaximizedBounds = Screen.FromControl(this).WorkingArea;   // taskbar-sicher
        RandAnwenden();   // erste Ziehzone (Padding steuert WebView-Flaeche + WM_NCHITTEST)
        base.OnLoad(e);
    }

    protected override void WndProc(ref Message m)
    {
        // Monitorwechsel auf andere Skalierung, Teil 1: WinForms beantwortet
        // WM_GETDPISCALEDSIZE mit der UNVERAENDERTEN Fensterflaeche - Windows
        // schlaegt dann in WM_DPICHANGED genau dieses Rechteck vor, das Fenster
        // behaelt also seine Pixelmasse (auf dem Zielfenster zu gross bzw.
        // zu klein) und das WebView2 bleibt auf dem Rueckweg im alten
        // Rastermassstab haengen ("alles sehr klein", Nutzer-Fall 11.10.2026).
        // Wir antworten deshalb SELBST mit linear skaliertem Rechteck
        // (neue DPI / alte DPI) - nur im Normalzustand, maximiert regelt das
        // System selbst.
        if (m.Msg == WM_GETDPISCALEDSIZE && WindowState == FormWindowState.Normal
            && Marshal.PtrToStructure(m.LParam, typeof(SkalierteGroesse)) is SkalierteGroesse anfrage)
        {
            double faktor = (double)(m.WParam.ToInt32() & 0xFFFF) / DeviceDpi;
            anfrage.Breite = (int)Math.Round(anfrage.Breite * faktor);
            anfrage.Hoehe = (int)Math.Round(anfrage.Hoehe * faktor);
            Marshal.StructureToPtr(anfrage, m.LParam, false);
            m.Result = (IntPtr)1;
            return;
        }
        // Teil 2: den (jetzt sinnvollen) Vorschlag tatsaechlich uebernehmen.
        // Erst base lassen (interne Font-/Skalierungspflege), dann anwenden.
        if (m.Msg == WM_DPICHANGED)
        {
            base.WndProc(ref m);
            if (WindowState == FormWindowState.Normal
                && Marshal.PtrToStructure(m.LParam, typeof(VorschlagsRect)) is VorschlagsRect v)
            {
                Bounds = new Rectangle(v.Links, v.Oben, v.Rechts - v.Links, v.Unten - v.Oben);
                Invalidate();
            }
            return;
        }
        // Groesse-Raender nur im Normalzustand und nur wo das WebView2 nicht ueberdeckt.
        // Greifbreite = ZiehzonePx (8/12), UNABHAENGIG vom schmalen Band-Padding:
        // die breite Zone ist unsichtbar ueber dem WebView-Rand (v0.21.9-Ergaenzung).
        if (m.Msg == WM_NCHITTEST && WindowState == FormWindowState.Normal && Padding.Left > 0)
        {
            int zone = ZiehzonePx();
            int zoneOben = ObengriffPx();
            int x = (short)(m.LParam.ToInt32() & 0xFFFF);
            int y = (short)((m.LParam.ToInt32() >> 16) & 0xFFFF);
            var p = PointToClient(new Point(x, y));
            bool links = p.X <= zone;
            bool rechts = p.X >= ClientSize.Width - zone;
            // OBERGRIFF (v0.21.34): die Oberkante war GAR NICHT greifbar
            // (Padding.Top 0 sperrte die Zone) und HTTOPLEFT/HTTOPRIGHT fehlten
            // - die Ecken oben liessen sich nur in der Breite ziehen
            // (Nutzer-Fund). Schmale Zone ueber der Kopfzeile, unsichtbar.
            bool oben = p.Y <= zoneOben;
            bool unten = p.Y >= ClientSize.Height - zone;
            if (links && unten) { m.Result = (IntPtr)HTBOTTOMLEFT; return; }
            if (rechts && unten) { m.Result = (IntPtr)HTBOTTOMRIGHT; return; }
            if (links && oben) { m.Result = (IntPtr)HTTOPLEFT; return; }
            if (rechts && oben) { m.Result = (IntPtr)HTTOPRIGHT; return; }
            if (oben) { m.Result = (IntPtr)HTTOP; return; }
            if (links) { m.Result = (IntPtr)HTLEFT; return; }
            if (rechts) { m.Result = (IntPtr)HTRIGHT; return; }
            if (unten) { m.Result = (IntPtr)HTBOTTOM; return; }
        }
        base.WndProc(ref m);
    }
}
