using System.Drawing.Printing;

namespace FederPDF;

/// <summary>Gemeinsame Blatt-Geometrie fuer DruckDialog (Vorschau) UND
/// Program (Druckauftrag): Blattmodell des gewaehlten Druckers, N-up-Gitter,
/// Zellen und Zell-Einpassen. Alle Masse in pt (1/72 Zoll), ausser wo eine
/// Methode explizit "gleiche Einheit fuer Seite und Zelle" verlangt - die
/// Verhaeltnis-Mathe ist Einheiten-unabhaengig (pt oder 1/100 Zoll), solange
/// beide Seiten derselben Einheit folgen.</summary>
internal static class DruckLayout
{
    /// <summary>Zwischenraum zwischen N-up-Zellen in pt.</summary>
    public const double Luecke = 6.0;

    /// <summary>N-up-Optionen des Druckdialogs (PDFgear-Auswahl).</summary>
    public static readonly int[] SeitenProBlattWerte = { 1, 2, 4, 6, 9, 16 };

    /// <summary>Blatt-Modell des GEWAEHLTEN Druckers in pt: Papierformat
    /// (1/100 Zoll x 0,72), bei Querformat vertauscht, plus druckbare Flaeche
    /// (orientierungskorrigiert, s. DruckbareFlaeche). Fehlschlag (Treiber
    /// ohne Daten, Offline-Drucker): A4 mit ueblichen 18-pt-Raendern - die
    /// Vorschau bleibt so immer zeichenfaehig. Nur-Namen-Daten, KEINE
    /// Statusabfrage (Pitfall: die blockiert an schlafenden Netzwerkdruckern).</summary>
    public static (double blattB, double blattH, RectangleF druckbar) BlattMasse(PrinterSettings ps)
    {
        double b = 595.0, h = 842.0;
        var druckbar = new RectangleF(18f, 18f, (float)(b - 36), (float)(h - 36));
        try
        {
            var dps = ps.DefaultPageSettings;
            var papier = dps.PaperSize;
            if (papier != null && papier.Width > 0 && papier.Height > 0)
            {
                b = papier.Width * 0.72;
                h = papier.Height * 0.72;
            }
            if (dps.Landscape) (b, h) = (h, b);
            druckbar = DruckbareFlaeche(dps, b, h);
        }
        catch { }
        return (b, h, druckbar);
    }

    /// <summary>Druckbare Flaeche einer PageSettings in pt, ORIENTIERUNGS-
    /// KORRIGIERT: PageSettings.PrintableArea folgt der Landscape-DEVMODE
    /// NICHT (Mess-Fund 31.10.2026, "Microsoft Print to PDF": unter Landscape
    /// meldet Bounds 1169x827, PrintableArea aber stur 827x1169 - die Kompo-
    /// sition blieb auf der linken Blatthaelfte). Massgabe ist die BLATT-Klasse
    /// (blattB/blattH - Bounds ist ausgerichtet): widerspricht die gemessene
    /// Flaeche der Blattklasse entscheidend, werden X/Y/W/H getauscht. Der
    /// 1,15-Vorbehalt verhindert Kippeln bei quadratnahen Blaettern.</summary>
    public static RectangleF DruckbareFlaeche(PageSettings seite, double blattB, double blattH)
    {
        var flaeche = new RectangleF(18f, 18f, (float)(blattB - 36), (float)(blattH - 36));
        try
        {
            var pa = seite.PrintableArea;   // 1/100 Zoll, NICHT zuverlaessig ausgerichtet
            float ax = Math.Max(0f, pa.X), ay = Math.Max(0f, pa.Y);
            float aw = Math.Max(1f, pa.Width - ax), ah = Math.Max(1f, pa.Height - ay);
            flaeche = new RectangleF(ax * 0.72f, ay * 0.72f, aw * 0.72f, ah * 0.72f);
            bool blattQuer = blattB > blattH * 1.15;
            bool blattHoch = blattH > blattB * 1.15;
            bool flaecheQuer = flaeche.Width > flaeche.Height * 1.15;
            bool flaecheHoch = flaeche.Height > flaeche.Width * 1.15;
            if ((blattQuer && flaecheHoch) || (blattHoch && flaecheQuer))
                flaeche = new RectangleF(flaeche.Y, flaeche.X, flaeche.Height, flaeche.Width);
            flaeche = RectangleF.Intersect(flaeche, new RectangleF(0f, 0f, (float)blattB, (float)blattH));
            if (flaeche.Width < 1f || flaeche.Height < 1f)
                flaeche = new RectangleF(18f, 18f, (float)(blattB - 36), (float)(blattH - 36));
        }
        catch { }
        return flaeche;
    }

    /// <summary>Bestes Spalten-x-Zeilen-Gitter fuer n Seiten pro Blatt:
    /// Kandidaten sind alle Faktorzerlegungen, gewaehlt wird die, deren
    /// Zell-Seitenverhaeltnis (nach Abzug der Zellabstaende) am naechsten am
    /// Seitenverhaeltnis der PDF-Seite liegt - 2 Seiten landen so nebeneinander
    /// auf Querblaettern und uebereinander auf Hochblaettern. Gleichstand
    /// (geometrisch gleichwertig, z. B. 2x1 vs 1x2 auf Hochformat): Leserichtung
    /// gewinnt, mehr Spalten.</summary>
    public static (int spalten, int zeilen) Gitter(int n, double druckbarB, double druckbarH,
                                                   double seiteB, double seiteH)
    {
        if (n <= 1) return (1, 1);
        double seitenAspekt = seiteH > 0.5 ? seiteB / seiteH : 0.707;   // Portrait-Fallback
        double beste = double.MaxValue;
        int besteSpalten = 1, besteZeilen = n;
        for (int c = 1; c <= n; c++)
        {
            if (n % c != 0) continue;
            int r = n / c;
            double b = Math.Max(1.0, druckbarB - Luecke * (c - 1));
            double h = Math.Max(1.0, druckbarH - Luecke * (r - 1));
            double zellAspekt = (b / c) / (h / r);
            double punkte = Math.Abs(Math.Log(zellAspekt / seitenAspekt));
            if (punkte < beste - 1e-9 || (Math.Abs(punkte - beste) <= 1e-9 && c > besteSpalten))
            {
                beste = punkte;
                besteSpalten = c;
                besteZeilen = r;
            }
        }
        return (besteSpalten, besteZeilen);
    }

    /// <summary>Rect einer Zelle (gleiche Einheit wie druckbar), Index HORIZONTAL
    /// zuerst (Leserichtung: erst Zeile, dann Spalte).</summary>
    public static RectangleF Zelle(RectangleF druckbar, int spalten, int zeilen, int ix)
    {
        int cx = ix % spalten, cy = ix / spalten;
        double abstandB = Luecke * (spalten - 1), abstandH = Luecke * (zeilen - 1);
        double bw = (druckbar.Width - abstandB) / spalten;
        double bh = (druckbar.Height - abstandH) / zeilen;
        return new RectangleF(
            (float)(druckbar.X + cx * (bw + Luecke)),
            (float)(druckbar.Y + cy * (bh + Luecke)),
            (float)bw, (float)bh);
    }

    /// <summary>Eine Seite in eine Zelle einpassen (gleiche Einheit fuer Seite
    /// und Zelle - pt fuer die Vorschau, 1/100 Zoll im Druck): Seitenverhaeltnis
    /// erhalten, zentriert. Einpass-Modus (skalierung &lt;= 0) dreht 90 Grad,
    /// WENN das gedreht mehr Flaeche nutzt - das verallgemeinert die bewaehrte
    /// Hoch/Quer-Kollision von SeiteEinpassen auf beliebig geformte Zellen.
    /// Fester Massstab (&gt; 0) dreht NIE. Rueckgabe-Ziel in derselben Einheit;
    /// die Drehung macht der Aufrufer am Bitmap (Rotate90FlipNone).</summary>
    public static (RectangleF ziel, bool drehen) SeiteInZelle(double seiteB, double seiteH,
                                                              RectangleF zelle, double skalierung)
    {
        bool drehen = false;
        double skala;
        if (skalierung <= 0)
        {
            double gerade = Math.Min(zelle.Width / seiteB, zelle.Height / seiteH);
            double gedreht = Math.Min(zelle.Width / seiteH, zelle.Height / seiteB);
            drehen = gedreht > gerade * 1.0001;   // Toleranz: nicht wegen Rundung kippen
            skala = Math.Max(gerade, gedreht);
        }
        else
        {
            skala = skalierung;
        }
        double b = seiteB * skala, h = seiteH * skala;
        return (new RectangleF(
            zelle.X + (float)((zelle.Width - b) / 2.0),
            zelle.Y + (float)((zelle.Height - h) / 2.0),
            (float)b, (float)h), drehen);
    }
}
