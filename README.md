# Amazon FC - przystanki autobusowe (scraper -> JSON)

**TL;DR:** Ten projekt zbiera publiczne informacje o przystankach i trasach autobusowych dla magazynów Amazon (FC) z serwisów `*.transport-fc.eu`, zapisuje je do `data/stops.json` oraz publikuje przez GitHub Pages. Aktualizacja odbywa się automatycznie (GitHub Actions). Front (strona na WordPress) pobiera ten JSON i rysuje najbliższe przystanki na mapie.

---

## Źródła danych (serwisy PARSOWANE)

Projekt parsuje publicznie dostępne strony sieci **transport-fc.eu** — m.in.:

- **WRO1–WRO4 (wspólny rozkład):** https://wro.transport-fc.eu/rozklady-jazdy/
- **WRO5:** https://wro5.transport-fc.eu/rozklady-jazdy/
- **LCJ2:** https://lcj2.transport-fc.eu/
- **LCJ3:** https://lcj3.transport-fc.eu/
- **LCJ4:** https://lcj4.transport-fc.eu/
- **Pozostałe przykładowe subdomeny:**  
  https://szz1.transport-fc.eu/, https://poz1.transport-fc.eu/, https://poz2.transport-fc.eu/,  
  https://ktw1.transport-fc.eu/, https://ktw3.transport-fc.eu/, https://ktw5.transport-fc.eu/

> Pełna lista aktualnie obsługiwanych subdomen jest w tablicy `FC_SUBS` w pliku `scraper/scrape_transport_fc.py`. Parser filtruje podstrony zawierające linki do **OpenStreetMap** i z nich wyciąga nazwy przystanków oraz współrzędne.

---

## Live JSON (GitHub Pages)

- **Aktualne dane:** `data/stops.json`  
  https://riteri.github.io/amazon-fc-stops/data/stops.json

- **Raport różnic:** `data/changes.json`  
  https://riteri.github.io/amazon-fc-stops/data/changes.json

> Jeśli forkujesz repozytorium — zmień `riteri/amazon-fc-stops` na swoją nazwę użytkownika/nazwę repo i włącz **GitHub Pages** (gałąź `main`, folder `/`).

---

## Jak to działa (architektura)

1. **GitHub Actions** uruchamia workflow wg harmonogramu (cron w **UTC**).  
2. Skrypt **Python** (`scraper/scrape_transport_fc.py`) odwiedza strony `*.transport-fc.eu`, znajduje linki OSM i zbiera przystanki (nazwa, lat, lon, kontekstowe godziny).  
3. Generowane są pliki:  
   - `data/stops.json` – pełna lista przystanków,  
   - `data/changes.json` – różnice względem poprzedniego przebiegu.  
4. Zmiany są **commitowane** do gałęzi `main`.  
5. **GitHub Pages** udostępnia pliki publicznie (URL powyżej).

### Uwaga na strefę czasu
- Cron w GitHub Actions jest **zawsze w UTC**.  
- Polska: **CEST (UTC+2)** latem, **CET (UTC+1)** zimą.  
- Przykład harmonogramu „dwa razy dziennie”: `7 */12 * * *` (00:07 i 12:07 UTC).
