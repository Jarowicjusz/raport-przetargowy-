#!/usr/bin/env python3
"""
Skrypt aktualizacji raportu przetargowego.
Uruchamiany przez GitHub Actions co tydzien.
Pobiera dane z portali przetargowych i aktualizuje index.html
"""

import requests
from bs4 import BeautifulSoup
import json, re, sys, datetime, shutil, time, os
from pathlib import Path
from urllib.parse import quote_plus

# index.html jest w katalogu glownym repo (GitHub Pages serwuje z root)
ROOT = Path(__file__).parent.parent
HTML_FILE = ROOT / "index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

FRAZY = [
    "system zarzadzania imprezami",
    "aplikacja mobilna event",
    "akredytacja uczestnikow",
    "platforma eventowa",
    "sprzedaz biletow system",
    "impreza masowa informatyczny",
    "aplikacja konferencyjna",
    "rejestracja uczestnikow wydarzenie",
    "ticketing system",
    "zarzadzanie wydarzeniami oprogramowanie",
]

# ──────────────────────────────────────────
#  ZRODLA DANYCH
# ──────────────────────────────────────────

def szukaj_egospodarka(fraza: str) -> list:
    """Przetargi z przetargi.egospodarka.pl"""
    url = f"https://przetargi.egospodarka.pl/szukaj/{quote_plus(fraza)}/0/1/"
    wyniki = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a", href=re.compile(r"/ogloszenie/\d+")):
            tytul = a.get_text(strip=True)
            if len(tytul) < 15:
                continue
            rodzic = a.find_parent(["tr", "li", "div"])
            zam, termin, nr, woj = "", "-", "", "Polska"
            if rodzic:
                tekst = rodzic.get_text(" ", strip=True)
                # Data
                dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tekst)
                if dm:
                    termin = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
                # Numer BZP
                nr_m = re.search(r"(\d{4}/BZP[\s\S]{5,30}?)\s", tekst)
                if nr_m:
                    nr = nr_m.group(1).strip()
                # Zamawiajacy
                for s in rodzic.find_all(["span", "td", "div", "p"]):
                    t = s.get_text(strip=True)
                    if 15 < len(t) < 120 and t != tytul and not re.search(r"\d{2}\.\d{2}\.\d{4}", t):
                        if not any(x in t.lower() for x in ["poprzedni", "nastepn", "strona"]):
                            zam = t
                            break

            wyniki.append({
                "tytul": tytul[:180],
                "zamawiajacy": zam,
                "termin": termin,
                "nr": nr,
                "woj": woj,
                "zrodlo": "BZP",
            })
            if len(wyniki) >= 10:
                break

    except Exception as e:
        print(f"    ⚠ egospodarka '{fraza[:30]}': {e}")
    return wyniki


def szukaj_atlas(fraza: str) -> list:
    """Przetargi z atlasprzetargow.pl"""
    url = f"https://atlasprzetargow.pl/przetargi?q={quote_plus(fraza)}&sort=date_desc"
    wyniki = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Szukaj kart przetargow - rozne selektory
        for selector in ["article", ".tender", "[class*='notice']", "[class*='result']", "li.item"]:
            karty = soup.select(selector)
            if karty:
                for karta in karty[:10]:
                    a = karta.select_one("a[href*='przetarg'], a[href*='notice'], h2 a, h3 a, .title a")
                    if not a:
                        continue
                    tytul = a.get_text(strip=True)
                    if len(tytul) < 15:
                        continue
                    tekst = karta.get_text(" ", strip=True)
                    termin = "-"
                    dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tekst)
                    if dm:
                        termin = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
                    iso = re.search(r"(\d{4}-\d{2}-\d{2})", tekst)
                    if iso:
                        termin = iso.group(1)
                    # Zamawiajacy
                    zam = ""
                    for el in karta.select(".buyer, .client, .zamawiajacy, [class*='buyer']"):
                        zam = el.get_text(strip=True)[:80]
                        break
                    wyniki.append({
                        "tytul": tytul[:180],
                        "zamawiajacy": zam,
                        "termin": termin,
                        "nr": "",
                        "woj": "Polska",
                        "zrodlo": "BZP",
                    })
                if wyniki:
                    break

    except Exception as e:
        print(f"    ⚠ atlas '{fraza[:30]}': {e}")
    return wyniki


def szukaj_pressinfo(fraza: str) -> list:
    """Przetargi z pressinfo.pl — publiczny podglad"""
    wyniki = []
    try:
        url = f"https://www.pressinfo.pl/search/apachesolr_search/{quote_plus(fraza)}?filters=type:tender"
        r = requests.get(url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a", href=re.compile(r"/przetarg/|/tender/")):
            tytul = a.get_text(strip=True)
            if len(tytul) < 15:
                continue
            rodzic = a.find_parent(["li", "div", "tr"])
            termin, zam = "-", ""
            if rodzic:
                tekst = rodzic.get_text(" ", strip=True)
                dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tekst)
                if dm:
                    termin = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
            wyniki.append({
                "tytul": tytul[:180],
                "zamawiajacy": zam,
                "termin": termin,
                "nr": "",
                "woj": "Polska",
                "zrodlo": "BZP",
            })
            if len(wyniki) >= 8:
                break
    except Exception as e:
        print(f"    ⚠ pressinfo '{fraza[:30]}': {e}")
    return wyniki


# ──────────────────────────────────────────
#  FILTROWANIE
# ──────────────────────────────────────────

SLOWA_EVENT = [
    "event", "impreza", "imprez", "konferencja", "konferencj", "kongres",
    "festiwal", "stadion", "akredytacja", "akredytacj", "bilet", "bilety",
    "ticketing", "aplikacja", "mobilna", "rejestracja", "organizacj",
    "uczestnik", "widownia", "hala", "arena", "widowisk", "platforma",
    "sportow", "rozrywk", "kulturalny", "zarzadzani",
]

def ocen(item: dict) -> int:
    tekst = (item.get("tytul", "") + " " + item.get("zamawiajacy", "")).lower()
    return min(sum(12 for w in SLOWA_EVENT if w in tekst), 100)


def deduplikuj(lista: list) -> list:
    seen, wynik = set(), []
    for x in lista:
        k = x.get("tytul", "")[:60].lower().strip()
        if k and len(k) > 10 and k not in seen:
            seen.add(k)
            wynik.append(x)
    return wynik


# ──────────────────────────────────────────
#  MAPOWANIE
# ──────────────────────────────────────────

def ustal_typ(z: str) -> str:
    n = z.upper()
    for s in ["PKP","PKO","PGE","KGHM","ORLEN","PERN","ENEA","TAURON","PZU","BGK","LOTOS","PGNIG","AZOTY"]:
        if s in n: return "SSP"
    for c in ["FILHARMON","OPERA","TEATR","MUZEUM","GALERIA","PKOL","KULTURY","FUNDACJA","OLIMP","MCK","CKiS"]:
        if c in n: return "CULT"
    return "MUN"


def ustal_kat(t: str) -> str:
    t = t.lower()
    if any(w in t for w in ["akredytacja","akredytacj","rejestracja uczest","badging"]): return "acc"
    if any(w in t for w in ["aplikacja mobilna","mobiln","ticketing","bilet","ios","android"]): return "app"
    return "plat"


def ustal_status(termin: str) -> str:
    if termin and termin != "-":
        try:
            if datetime.datetime.strptime(termin, "%Y-%m-%d") < datetime.datetime.now():
                return "eval"
        except ValueError:
            pass
    return "new"


def mapuj(item: dict, idx: int) -> dict:
    tytul = item.get("tytul", "Brak tytulu")[:180]
    t = tytul.lower()
    tagi = []
    for slowo, tag in [
        ("rfid","RFID"),("qr","QR kod"),("mobiln","aplikacja mobilna"),
        ("stadion","stadion"),("arena","arena"),("konferencj","konferencja"),
        ("festiwal","festiwal"),("bilet","ticketing"),("akredytacj","akredytacja"),
        ("imprez","impreza masowa"),("rejestr","rejestracja"),("saas","SaaS"),
    ]:
        if slowo in t:
            tagi.append(tag)
        if len(tagi) >= 3:
            break
    if not tagi:
        tagi = ["system IT", "zamowienie publiczne"]

    zam = item.get("zamawiajacy", "") or "Zamawiajacy publiczny"
    termin = item.get("termin", "-")

    return {
        "id": f"PT{idx:03d}",
        "title": tytul,
        "zam": zam,
        "typ": ustal_typ(zam),
        "kat": ustal_kat(tytul),
        "status": ustal_status(termin),
        "wartosc": "Nie podano",
        "termin": termin,
        "nr": item.get("nr") or f"2026/BZP-{idx:06d}",
        "zrodlo": item.get("zrodlo", "BZP"),
        "woj": item.get("woj", "Polska"),
        "opis": tytul,
        "tagi": tagi[:4],
    }


# ──────────────────────────────────────────
#  AKTUALIZACJA HTML
# ──────────────────────────────────────────

def aktualizuj_html(przetargi: list):
    if not HTML_FILE.exists():
        print(f"BLAD: brak pliku {HTML_FILE}")
        sys.exit(1)

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    nowe = json.dumps(przetargi, ensure_ascii=False, indent=2)
    nowy = re.sub(r"const DATA = \[[\s\S]*?\];", f"const DATA = {nowe};", html)

    now = datetime.datetime.now()
    tydzien = now.isocalendar()[1]
    nowy = re.sub(r"Tydzie[ń\u0144n] \d+ / \d+", f"Tydzień {tydzien} / {now.year}", nowy)

    # Ustaw zmienna srodowiskowa dla workflow
    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a") as f:
            f.write(f"DATA_AKTUALIZACJI={now.strftime('%d.%m.%Y')}\n")
            f.write(f"TYDZIEN={tydzien}/{now.year}\n")

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(nowy)

    print(f"  ✅ Zaktualizowano: {HTML_FILE.name}")
    print(f"  📊 Przetargow: {len(przetargi)}")
    print(f"  📅 Tydzien: {tydzien}/{now.year}")


# ──────────────────────────────────────────
#  MAIN
# ──────────────────────────────────────────

def main():
    print("=" * 55)
    print("  AKTUALIZACJA RAPORTU PRZETARGOWEGO")
    print(f"  {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')} UTC")
    print("=" * 55)

    wszystkie = []

    for i, fraza in enumerate(FRAZY, 1):
        print(f"\n  [{i}/{len(FRAZY)}] '{fraza}'")

        print("    → egospodarka.pl ", end="", flush=True)
        w = szukaj_egospodarka(fraza)
        print(f"({len(w)})")
        wszystkie.extend(w)

        print("    → atlasprzetargow.pl ", end="", flush=True)
        w = szukaj_atlas(fraza)
        print(f"({len(w)})")
        wszystkie.extend(w)

        print("    → pressinfo.pl ", end="", flush=True)
        w = szukaj_pressinfo(fraza)
        print(f"({len(w)})")
        wszystkie.extend(w)

        time.sleep(1)  # grzeczne pobieranie

    print(f"\n  Zebrano lacznie: {len(wszystkie)}")

    # Pokaz probke
    print("\n  Przykladowe tytuly (pierwsze 5):")
    for x in wszystkie[:5]:
        print(f"    [{ocen(x):3d}] {x.get('tytul','')[:70]}")

    trafne = [x for x in wszystkie if ocen(x) >= 12]
    print(f"\n  Trafnych (prog 12): {len(trafne)}")

    # Jesli za malo - obniz prog
    if len(trafne) < 5:
        print("  Za malo wynikow — obniżam prog do 0")
        trafne = [x for x in wszystkie if len(x.get("tytul", "").strip()) > 15]

    unikalne = deduplikuj(trafne)
    print(f"  Unikalnych: {len(unikalne)}")

    if not unikalne:
        print("\n  ⚠ Brak wynikow — portale niedostepne.")
        print("  Plik HTML nie zostanie zmieniony.")
        sys.exit(0)

    przetargi = [mapuj(x, i + 1) for i, x in enumerate(unikalne)]

    print(f"\n  Aktualizacja pliku HTML...")
    aktualizuj_html(przetargi)

    n = sum(1 for p in przetargi if p["status"] == "new")
    e = sum(1 for p in przetargi if p["status"] == "eval")

    print(f"""
  ╔══════════════════════════════════════╗
  ║  GOTOWE ✅                           ║
  ╠══════════════════════════════════════╣
  ║  Przetargow: {len(przetargi):<25}║
  ║  Nowych:     {n:<25}║
  ║  W ocenie:   {e:<25}║
  ╚══════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
