Widzę — API BZP zwraca 0 dla wszystkich zapytań. To znaczy że ten endpoint nie działa publicznie bez autoryzacji.

Muszę zmienić podejście — zamiast API użyję **bezpośredniego scrapingu strony BZP** która jest publiczna. Wklej to w edytorze GitHub (tak samo jak poprzednio):

**https://github.com/Jarowicjusz/raport-przetargowy-/edit/main/scripts/aktualizuj_raport.py**

```python
#!/usr/bin/env python3
import requests, json, re, sys, datetime, time, os
from pathlib import Path
from urllib.parse import quote_plus
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent.parent
HTML_FILE = ROOT / "index.html"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

FRAZY = [
    "aplikacja+mobilna+impreza",
    "system+akredytacji+uczestnikow",
    "platforma+zarzadzania+eventami",
    "system+sprzedazy+biletow",
    "aplikacja+konferencyjna",
    "system+rejestracji+uczestnikow",
    "impreza+masowa+system+informatyczny",
    "ticketing+oprogramowanie",
]

SLOWA_EVENT = [
    "event","impreza","imprez","konferencja","kongres","festiwal",
    "stadion","akredytacja","bilet","ticketing","aplikacja","mobilna",
    "rejestracja","uczestnik","widownia","hala","arena","platforma",
]

def szukaj_bzp(fraza):
    url = f"https://przetargi.egospodarka.pl/szukaj/{quote_plus(fraza)}/0/1/"
    wyniki = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/ogloszenie/\d+")):
            tytul = a.get_text(strip=True)
            if len(tytul) < 20: continue
            href = a.get("href","")
            link = f"https://przetargi.egospodarka.pl{href}" if href.startswith("/") else href
            rodzic = a.find_parent(["tr","li","div"])
            zam, termin, nr = "", "-", ""
            if rodzic:
                tekst = rodzic.get_text(" ", strip=True)
                dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tekst)
                if dm: termin = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
                nm = re.search(r"(\d{4}/BZP[^\s]{5,25})", tekst)
                if nm: nr = nm.group(1)
                for s in rodzic.find_all(["span","td","div","p"]):
                    t = s.get_text(strip=True)
                    if 15 < len(t) < 100 and t != tytul and not re.search(r"\d{2}\.\d{2}\.\d{4}",t):
                        zam = t; break
            wyniki.append({"tytul":tytul[:180],"zam":zam,"termin":termin,"nr":nr,"link":link})
            if len(wyniki) >= 10: break
    except Exception as e:
        print(f"  blad: {e}")
    return wyniki

def szukaj_bzp2(fraza):
    url = f"https://www.przetargi.info/szukaj?q={quote_plus(fraza)}"
    wyniki = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=re.compile(r"/przetarg/\d+|/notice/")):
            tytul = a.get_text(strip=True)
            if len(tytul) < 20: continue
            href = a.get("href","")
            link = f"https://www.przetargi.info{href}" if href.startswith("/") else href
            rodzic = a.find_parent(["tr","li","div","article"])
            termin = "-"
            if rodzic:
                tekst = rodzic.get_text(" ", strip=True)
                dm = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", tekst)
                if dm: termin = f"{dm.group(3)}-{dm.group(2)}-{dm.group(1)}"
                iso = re.search(r"(\d{4}-\d{2}-\d{2})", tekst)
                if iso: termin = iso.group(1)
            wyniki.append({"tytul":tytul[:180],"zam":"","termin":termin,"nr":"","link":link})
            if len(wyniki) >= 8: break
    except Exception as e:
        print(f"  blad przetargi.info: {e}")
    return wyniki

def ocen(item):
    t = item.get("tytul","").lower()
    return min(sum(15 for w in SLOWA_EVENT if w in t), 100)

def ustal_typ(z):
    n = z.upper()
    for s in ["PKP","PKO","PGE","KGHM","ORLEN","PERN","ENEA","TAURON","PZU","BGK","LOTOS","PGNIG"]:
        if s in n: return "SSP"
    for c in ["FILHARMON","OPERA","TEATR","MUZEUM","GALERIA","PKOL","KULTURY","FUNDACJA","OLIMP","MCK"]:
        if c in n: return "CULT"
    return "MUN"

def ustal_kat(t):
    t = t.lower()
    if any(w in t for w in ["akredytacja","rejestracja uczest"]): return "acc"
    if any(w in t for w in ["mobiln","ticketing","bilet","ios","android"]): return "app"
    return "plat"

def ustal_status(termin):
    if termin and termin != "-":
        try:
            if datetime.datetime.strptime(termin[:10],"%Y-%m-%d") < datetime.datetime.now():
                return "eval"
        except: pass
    return "new"

def mapuj(item, idx):
    tytul = item.get("tytul","Brak")[:180]
    t = tytul.lower()
    tagi = []
    for s,g in [("akredytacj","akredytacja"),("bilet","ticketing"),("mobiln","aplikacja mobilna"),
                ("stadion","stadion"),("konferencj","konferencja"),("festiwal","festiwal"),
                ("imprez","impreza"),("rejestr","rejestracja")]:
        if s in t: tagi.append(g)
        if len(tagi)>=3: break
    if not tagi: tagi=["system IT","zamowienie publiczne"]
    zam = item.get("zam","") or "Zamawiajacy publiczny"
    termin = item.get("termin","-")
    nr = item.get("nr") or f"BZP-{idx:06d}"
    link = item.get("link") or f"https://przetargi.egospodarka.pl/szukaj/{quote_plus(tytul[:40])}/0/1/"
    return {
        "id":f"PT{idx:03d}","title":tytul,"zam":zam,
        "typ":ustal_typ(zam),"kat":ustal_kat(tytul),"status":ustal_status(termin),
        "wartosc":"Nie podano","termin":termin,"nr":nr,"link":link,"zrodlo":"BZP",
        "woj":"Polska","opis":tytul,"tagi":tagi[:4],
    }

def aktualizuj_html(przetargi):
    with open(HTML_FILE,"r",encoding="utf-8") as f: html=f.read()
    nowe = json.dumps(przetargi,ensure_ascii=False,indent=2)
    nowy = re.sub(r"const DATA = \[[\s\S]*?\];",f"const DATA = {nowe};",html)
    now = datetime.datetime.now()
    nowy = re.sub(r"Tydzie[ń\u0144n] \d+ / \d+",f"Tydzień {now.isocalendar()[1]} / {now.year}",nowy)
    if "GITHUB_ENV" in os.environ:
        with open(os.environ["GITHUB_ENV"],"a") as f:
            f.write(f"DATA_AKTUALIZACJI={now.strftime('%d.%m.%Y')}\n")
    with open(HTML_FILE,"w",encoding="utf-8") as f: f.write(nowy)
    print(f"Zaktualizowano: {len(przetargi)} przetargow")

def main():
    print("="*50)
    print(f"AKTUALIZACJA {datetime.datetime.now().strftime('%d.%m.%Y %H:%M')} UTC")
    print("="*50)
    wszystkie = []
    for fraza in FRAZY:
        print(f"  egospodarka: '{fraza}'", end=" ", flush=True)
        w = szukaj_bzp(fraza)
        print(f"-> {len(w)}")
        wszystkie.extend(w)
        time.sleep(1)
    for fraza in FRAZY[:4]:
        print(f"  przetargi.info: '{fraza}'", end=" ", flush=True)
        w = szukaj_bzp2(fraza)
        print(f"-> {len(w)}")
        wszystkie.extend(w)
        time.sleep(1)
    print(f"\nZebrano: {len(wszystkie)}")
    trafne = [x for x in wszystkie if ocen(x) >= 15]
    print(f"Trafnych: {len(trafne)}")
    if not trafne:
        print("Biorę wszystkie niepuste")
        trafne = [x for x in wszystkie if len(x.get("tytul","")) > 20]
    seen, unikalne = set(), []
    for x in trafne:
        k = x.get("tytul","")[:60].lower()
        if k and k not in seen: seen.add(k); unikalne.append(x)
    print(f"Unikalnych: {len(unikalne)}")
    for x in unikalne[:3]:
        print(f"  -> {x['tytul'][:60]}")
        print(f"     {x['link'][:80]}")
    if not unikalne:
        print("Brak wynikow."); sys.exit(0)
    przetargi = [mapuj(x,i+1) for i,x in enumerate(unikalne[:20])]
    aktualizuj_html(przetargi)
    print(f"GOTOWE — {len(przetargi)} przetargow")

if __name__ == "__main__":
    main()
```

Wklej, zapisz, uruchom Actions ponownie.
