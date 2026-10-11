# Träningsdashboard på Vercel

Webbsidan visar **verkliga mätvärden** från Python-träningen. Kurvor, steg, antal
avslutade försök, tidsåtgång och träningshastighet rapporteras av `TrainingReporter`.
Canvas-spelaren återger sparade positioner och handlingar från `DashEnv`; den kör
inte en separat JavaScript-fysik eller en handkodad spelare.

Python-träningen körs på din dator. Vercel serverar webbgränssnittet och tar emot
rapporter. Webbplatsen startar inga träningsjobb på Vercel.

## Se sidan lokalt

Använd Node.js 22 eller senare:

```bash
npm run dev
```

Öppna `http://127.0.0.1:5173`. Sidan innehåller redan en verklig sparad
träningskörning och en inspelning från demomodellen. Det behövs inga npm-paket.

I en annan terminal, från samma projektmapp:

```bash
source .venv/bin/activate
geodaish train --steps 2000000
```

Träningen skriver atomiskt till `runs/live.json`, som den lokala webbservern
läser. Webbsidan väljer den senaste körningen automatiskt. Välj **Sparad
demokörning** i menyn om du vill jämföra med de medföljande resultaten.

## Publicera på Vercel

1. Importera `oskar-cloud/Geodaish` från GitHub i Vercel.
2. Root Directory: projektets rot, inte `web/`.
3. Framework Preset: **Other**. Build Command: **npm run build**.
4. Output Directory: **dist**. `vercel.json` innehåller dessa inställningar.
5. Deploy. Den sparade körningen fungerar direkt, även utan backendinställningar.

Bygget kopierar bara `web/` till `dist/`. Python, modellvikter, lokala loggar och
inloggningsuppgifter är inte del av det statiska bygget. `api/training.js` körs
separat som en Node.js-funktion på Vercel.

## Koppla live från Macen till Vercel

### 1. Lagring

Lägg till **Upstash Redis** via Vercels Storage/Marketplace och anslut databasen
till projektets Production-miljö. Servern stöder följande miljövariabler:

| Alternativ | REST-adress | Skrivtoken |
|---|---|---|
| Upstash | `UPSTASH_REDIS_REST_URL` | `UPSTASH_REDIS_REST_TOKEN` |
| Vercel KV-prefix | `KV_REST_API_URL` | `KV_REST_API_TOKEN` |

REST-token måste tillåta läsning och skrivning. Använd ingen `VITE_`- eller annan
frontendprefix på hemligheter. Redis-värdena används bara av Vercel-servern och
behövs inte på träningsdatorn.

### 2. En nyckel för rapportering

Skapa en slumpmässig nyckel i din egen terminal:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Lägg värdet som `TRAINING_API_TOKEN` i Vercels Environment Variables för
Production. Gör en ny deployment när miljövariablerna är satta. Lägg aldrig
nyckeln i GitHub eller i webbläsarens JavaScript.

### 3. Starta träningen

Aktivera Python-miljön och kör följande i terminalen. När `read` väntar, klistra
in samma nyckel som ovan och tryck Enter. Inmatningen visas inte på skärmen.

```bash
source .venv/bin/activate
export GEODAISH_DASHBOARD_URL="https://ditt-projekt.vercel.app"
read -s GEODAISH_DASHBOARD_TOKEN
export GEODAISH_DASHBOARD_TOKEN
geodaish train --steps 2000000 --output runs/live-session-1
```

Använd projektets kanoniska produktionsadress. Rapport-API:t behöver vara
nåbart från Macen. En Vercel Preview-adress bakom Deployment Protection tar
inte emot rapporter utan särskild konfigurering; använd normalt Production.

Träningen skriver alltid den lokala rapporten och laddar dessutom upp till
`POST /api/training`. Uppladdningen sker i en bakgrundstråd med en kö som håller
det senaste värdet. Tillfälliga nätfel får begränsade återförsök. Permanent fel
eller nekad inloggning visas i terminalen; träningen fortsätter lokalt.

Sidan hämtar data ungefär var femte sekund medan fliken är synlig. Rapporter
kommer var femte sekund och vid validering. Slutrapporten skickas även vid
normal avslutning eller Ctrl+C. Längre validering eller nätfördröjning kan ge
större intervall. Efter 20 sekunder utan data markeras körningen som fördröjd;
sidan hittar inte på nya värden. Uppspelningen kommer efter första valideringen
och visar **modellen vid just den valideringen**, inte en direktvideoström av
alla parallella miljöer.

Dashboarden lagrar ett senaste träningspass åt gången i Redis. Nya pass ersätter
äldre. Fördröjda paket från äldre pass eller med äldre sekvensnummer avvisas
atomiskt. Kurvan i en liverapport rymmer de senaste 1 000 valideringarna; kompletta
CSV-loggar ligger kvar i körningens katalog. Använd en ny `--output`-katalog för
varje pass. Återupptagen träning visar både kumulativa steg och nya steg i passet.

Alla besökare som kan öppna webbplatsen kan läsa träningsmåtten och uppspelningen.
Skrivning kräver rapporteringsnyckeln. Rapporten innehåller inga hemligheter eller
absoluta sökvägar. Tjänsternas lagrings- och trafikgränser gäller; kontrollera
Vercel/Upstash-planen du väljer. Besökare gör en lagringsläsning per uppdatering.

## Exportera en annan sparad körning

```bash
geodaish export-dashboard \
  --run runs/normal-continued \
  --model models/demo-normal.zip \
  --evaluation docs/evaluation-normal.json \
  --output web/data/demo.json
```

`--evaluation` är frivilligt och ska vara ett separat sluttest för den angivna
modellen. Den exporterade demon återger CSV-värden från träningspasset och en
ny deterministisk uppspelning av den sparade modellen. Äldre loggar saknar exakta
tider för varje valideringspunkt; dessa tider lämnas tomma. Inga tider gissas.
Demoexporten kräver hela den lokala körningsmappen, som inte checkas in.

För en ny statisk demo: exportera, committa `web/data/demo.json` och pusha till
GitHub. Vercel bygger om sidan. För liverapportering behövs inga nya Git-pushar.

## Felsökning

| Symtom | Betydelse/åtgärd |
|---|---|
| Sparad körning visas | Ingen liverapport är tillgänglig ännu, eller demon är vald i menyn. |
| HTTP 401 i träningsloggen | Kontrollera att nycklarna matchar och har minst 32 tecken. |
| HTTP 503 | Redis-variabler saknas på Vercel; koppla lagringen och gör en ny deployment. |
| HTTP 502 | Servern kunde inte läsa/skriva Redis. Kontrollera REST-token och tjänstens status. |
| HTTP 409 | En nyare körning/rapport finns redan. Undvik flera samtidiga pass till samma dashboard. |
| Inga nya data | Macen kan vara pausad/offline eller upptagen; senaste verkliga värden ligger kvar. |
| Ingen uppspelning ännu | Första valideringen har inte slutförts. |

## Verifiering

```bash
python -m pytest -q
npm test
npm run build
```

Tester kontrollerar bland annat att replay-bildrutor matchar Python-fysiken,
att slutrapporten sparas, att nätfel inte tappar den lokala rapporten, att
obehöriga uppladdningar nekas och att sparad eller fördröjd data inte visas som
aktiv träning. API-tester använder en simulerad Redis-transport; ett riktigt
Vercel/Upstash-projekt måste konfigureras innan en livekoppling kan verifieras där.

Referenser: [Vercels Node.js-funktioner](https://vercel.com/docs/functions/runtimes/node-js)
och [Upstash Redis REST API](https://upstash.com/docs/redis/features/restapi).

## Geometry Dash live från Windows

Den separata sidan `/windows.html` visar Windows-adapterns verkliga detektioner,
hoppstatus och valbara beskurna spelbilder. Den använder `/api/windows` och en
separat Redis-nyckel med samma serverinställningar. Se
[Windows-guiden](windows-adapter.md#publicera-dashboarden-på-vercel) för kommandon,
stoppfunktion och vad som faktiskt har testats.
