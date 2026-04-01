#!/usr/bin/env python3
import requests, json, re, sys, datetime, time, os
from pathlib import Path
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
HTML_FILE = ROOT / "index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

FRAZY = [
    "aplikacja mobilna impreza",
    "system akredytacji uczestnikow",
    "platforma eventowa",
    "system sprzedazy biletow",
    "aplikacja konferencyjna",
    "system rejestracji uczestnikow",
    "impreza masowa system",
    "ticketing oprogramowanie",
]

SLOWA_EVENT = [
    "event", "impreza", "imprez", "konferencja", "kongres", "festiwal",
    "stadion", "akredytacja", "bilet", "ticketing", "aplikacja", "mobilna",
    "rejestracja", "uczestnik", "widownia", "hala", "arena", "platforma",
]


def szukaj_egospodarka(fraza):
    url = "https://przetargi.egospodarka.pl/szukaj/{}/0/1/".format(quote_plus(fraza))
    wyniki = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/ogloszenie/\d+")):
            tytul = a.get_text(strip=True)
            if len(tytul) < 20:
                continue
            href = a.get("href", "")
            link = "https://przetargi.egospodarka.pl{}".format(href) if href.startswith("/") else href
            rodzic = a.find_parent(["tr", "li", "div"])
            zam, termin, nr = "", "-", ""
            if rodzic:
                tekst = rodzic.get_text(" ", strip=True)
                dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tekst)
                if dm:
                    termin = "{}-{}-{}".format(dm.group(3), dm.group(2), dm.group(1))
                nm = re.search(r"(\d{4}/BZP[^\s]{5,25})", tekst)
                if nm:
                    nr = nm.group(1)
                for s in rodzic.find_all(["span", "td", "div", "p"]):
                    t = s.get_text(strip=True)
                    if 15 < len(t) < 100 and t != tytul and not re.search(r"\d{2}\.\d{2}\.\d{4}", t):
                        zam = t
                        break
            wyniki.append({"tytul": tytul[:180], "zam": zam, "termin": termin, "nr": nr, "link": link})
            if len(wyniki) >= 10:
                break
    except Exception as e:
        print("  blad egospodarka: {}".format(e))
    return wyniki


def szukaj_pressinfo(fraza):
    url = "https://www.pressinfo.pl/search/apachesolr_search/{}?filters=type:tender".format(quote_plus(fraza))
    wyniki = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/przetarg/|/tender/")):
            tytul = a.get_text(strip=True)
            if len(tytul) < 20:
                continue
            href = a.get("href", "")
            link = "https://www.pressinfo.pl{}".format(href) if href.startswith("/") else href
            rodzic = a.find_parent(["li", "div", "tr"])
            termin = "-"
            if rodzic:
                tekst = rodzic.get_text(" ", strip=True)
                dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tekst)
                if dm:
                    termin = "{}-{}-{}".format(dm.group(3), dm.group(2), dm.group(1))
            wyniki.append({"tytul": tytul[:180], "zam": "", "termin": termin, "nr": "", "link": link})
            if len(wyniki) >= 8:
                break
    except Exception as e:
        print("  blad pressinfo: {}".format(e))
    return wyniki


def ocen(item):
    t = item.get("tytul", "").lower()
    return min(sum(15 for w in SLOWA_EVENT if w in t), 100)


def ustal_typ(z):
    n = z.upper()
    for s in ["PKP", "PKO", "PGE", "KGHM", "ORLEN", "PERN", "ENEA", "TAURON", "PZU", "BGK", "LOTOS", "PGNIG"]:
        if s in n:
            return "SSP"
    for c in ["FILHARMON", "OPERA", "TEATR", "MUZEUM", "GALERIA", "PKOL", "KULTURY", "FUNDACJA", "OLIMP", "MCK"]:
        if c in n:
            return "CULT"
    return "MUN"


def ustal_kat(t):
    t = t.lower()
    if any(w in t for w in ["akredytacja", "rejestracja uczest"]):
        return "acc"
    if any(w in t for w in ["mobiln", "ticketing", "bilet", "ios", "android"]):
        return "app"
    return "plat"


def ustal_status(termin):
    if termin and termin != "-":
        try:
            if datetime.datetime.strptime(termin[:10], "%Y-%m-%d") < datetime.datetime.now():
                return "eval"
        except Exception:
            pass
    return "new"


def mapuj(item, idx):
    tytul = item.get("tytul", "Brak")[:180]
    t = tytul.lower()
    tagi = []
    for s, g in [
        ("akredytacj", "akredytacja"), ("bilet", "ticketing"), ("mobiln", "aplikacja mobilna"),
        ("stadion", "stadion"), ("konferencj", "konferencja"), ("festiwal", "festiwal"),
        ("imprez", "impreza"), ("rejestr", "rejestracja")
    ]:
        if s in t:
            tagi.append(g)
        if len(tagi) >= 3:
            break
    if not tagi:
        tagi = ["system IT", "zamowienie publiczne"]
    zam = item.get("zam", "") or "Zamawiajacy publiczny"
    termin = item.get("termin", "-")
    nr = item.get("nr") or "BZP-{:06d}".format(idx)
    link = item.get("link") or "https://przetargi.egospodarka.pl/szukaj/{}/0/1/".format(quote_plus(tytul[:40]))
    return {
        "id": "PT{:03d}".format(idx),
        "title": tytul,
        "zam": zam,
        "typ": ustal_typ(zam),
        "kat": ustal_kat(tytul),
        "status": ustal_status(termin),
        "wartosc": "Nie podano",
        "termin": termin,
        "nr": nr,
        "link": link,
        "zrodlo": "BZP",
        "woj": "Polska",
        "opis": tytul,
        "tagi": tagi[:4],
    }


def aktualizuj_html(przetargi):
    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()
    nowe = json.dumps(przetargi, ensure_ascii=False, indent=2)
    nowy = re.sub(r"const DATA = \[[\s\S]*?\];", "const DATA = {};".format(nowe), html)
    now = datetime.datetime.now()
    nowy = re.sub(r"Tydzie[n\u0144] \d+ / \d+", "Tydzien {} / {}".format(now.isocalendar()[1], now.year), nowy)
    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"], "a") as f:
            f.write("DATA_AKTUALIZACJI={}\n".format(now.strftime("%d.%m.%Y")))
    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(nowy)
    print("Zaktualizowano: {} przetargow".format(len(przetargi)))


def main():
    print("=" * 50)
    print("AKTUALIZACJA {}".format(datetime.datetime.now().strftime("%d.%m.%Y %H:%M UTC")))
    print("=" * 50)

    wszystkie = []

    for fraza in FRAZY:
        print("egospodarka: '{}'".format(fraza), end=" ", flush=True)
        w = szukaj_egospodarka(fraza)
        print("-> {}".format(len(w)))
        wszystkie.extend(w)
        time.sleep(1)

    for fraza in FRAZY[:4]:
        print("pressinfo: '{}'".format(fraza), end=" ", flush=True)
        w = szukaj_pressinfo(fraza)
        print("-> {}".format(len(w)))
        wszystkie.extend(w)
        time.sleep(1)

    print("\nZebrano: {}".format(len(wszystkie)))

    trafne = [x for x in wszystkie if ocen(x) >= 15]
    print("Trafnych: {}".format(len(trafne)))

    if not trafne:
        print("Biorę wszystkie z sensownym tytulem")
        trafne = [x for x in wszystkie if len(x.get("tytul", "")) > 20]

    seen = set()
    unikalne = []
    for x in trafne:
        k = x.get("tytul", "")[:60].lower()
        if k and k not in seen:
            seen.add(k)
            unikalne.append(x)

    print("Unikalnych: {}".format(len(unikalne)))

    for x in unikalne[:3]:
        print("  -> {}".format(x["tytul"][:70]))
        print("     {}".format(x["link"][:80]))

    if not unikalne:
        print("Brak wynikow.")
        sys.exit(0)

    przetargi = [mapuj(x, i + 1) for i, x in enumerate(unikalne[:20])]
    aktualizuj_html(przetargi)
    print("GOTOWE - {} przetargow".format(len(przetargi)))


if __name__ == "__main__":
    main()
