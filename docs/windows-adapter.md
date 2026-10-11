# Geometry Dash på Windows och live på Vercel

Adaptern läser **det verkliga Steam-spelets klientyta** med MSS, hittar en
kalibrerad färgad kub och ljusa triangulära spikar och skickar samma 16 tal som
`DashEnv` till PPO. Hopp hålls/släpps med Windows `SendInput`. Modellen tränas
fortfarande i simulatorn; `windows run` uppdaterar inga modellvikter.

## Vad som faktiskt testats

2026-10-11, ett fönster på 1480 × 833 klientpixlar, normal gravitation och den
platta inledningen av **Stereo Madness**. Ingen egen bana skapades i originalets
editor. Detaljer och numeriska resultat finns i [windows-results.json](windows-results.json).

- Kub och enskilda spikar kontrollerades visuellt mot sparade spelbilder.
- Ett isolerat hopp och en landning mättes från sju luftburna bildrutor.
- `models/demo-normal.zip` hoppade över de första enskilda spikarna. Adaptern
  stoppade när block kom in i synfältet, ungefär vid 4,4 % av banan.
- Uppåtpilen fungerade. Mellanslag gav inget hopp i den aktuella spelkonfigurationen.
  Välj därför `--jump-key up` på den här datorn; välj den bindning som faktiskt
  fungerar manuellt på andra datorer.
- 20 000 steg fortsatt PPO-träning med uppmätt fysik och uppskattad fördröjning
  klarade den fasta simulatorbanan, även med bildobservationer. Den modellen
  stoppade också vid blocken i originalet. Det bevisar ingen förbättring på en
  hel originalbana eller generalisering till nya banor.
- STOP-knappen och F9 testades på Windows och avslutade sessionerna. F9
  registreras som en global Windows-snabbtangent, så även korta tryck köas.
- Lokal livevy, API-validering och lagringsanrop med mockad Redis testades.
  Extern Vercel/Redis-installation och uppladdning har inte testats.

## Installera och kontrollera bilden

Från repots rot, med Python 3.12 på Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[windows,dev]"
```

Starta Steam-spelet i fönsterläge. Håll hela klientytan på skärmen, med tydligt
färgad kub och normal storlek, platt mark och ljusa spikar. Stäng överlägg som
kan täcka spelområdet. Börja på en fri startsträcka och byt till spelet under
kommandots tre sekunders väntetid:

```powershell
.\.venv\Scripts\python.exe -m geodaish windows capture --output runs/windows/screen.png
.\.venv\Scripts\python.exe -m geodaish windows calibrate --image runs/windows/screen.png
```

Markera hela den upprätta kuben på marken och tryck Enter. Klicka sedan på
marklinjens överkant. En pausmeny dimmar bilden och fungerar inte som kalibrering.
Om bilden visar ett hopp: ta en ny bild. Samma bildproportioner kan skalas till
en annan fönsterstorlek före armering. Ny kubfärg, ändrat bildformat eller
kameraläge kräver ny kalibrering. Storleksändring under styrning stoppar försöket.
Det går också att ange `--cube X Y BREDD HÖJD --ground-y Y` utan urvalsfönster.

```powershell
.\.venv\Scripts\python.exe -m geodaish windows detect --image runs/windows/screen.png --profile runs/windows/profile.json
.\.venv\Scripts\python.exe -m geodaish windows preview --profile runs/windows/profile.json --local-only
```

Kontrollera gula ramar kring kub/spikar och grön marklinje. **Preview skickar
inga hopp.** Klicka tillbaka till Geometry Dash för att få färska bilder;
förhandsvisningens eget fönster ska ligga bredvid spelet. Hastigheten behöver
minst två bilder av rörliga spikar. Bakgrundsrörelse håller spårningen aktiv
mellan spikarna men används inte för att uppskatta löphastigheten.

## Kör PPO och stoppa

```powershell
.\.venv\Scripts\python.exe -m geodaish windows run --profile runs/windows/profile.json --model models/demo-normal.zip --jump-key up --local-only
```

Välj Geometry Dash och tryck **F8**, eller välj **ARM in 3 seconds** och återgå
till spelet. Första modellbeslutet kräver en tillförlitlig rörlig scen.
I `windows run` behöver du bara aktivera en gång: slå på **Auto-Retry** i spelet.
När kuben försvinner eller ett hinder saknar stöd släpper adaptern hoppknappen
och visar **VÄNTAR PÅ NYTT FÖRSÖK**. Efter att kuben försvunnit i minst två bilder
och sedan åter syns på platt mark med rörelse, synliga spikar och fri ansats i
tre stabila bilder fortsätter PPO automatiskt. Adaptern klickar inte i menyer
eller trycker någon omstartstangent. Du kan även starta om banan manuellt inne
i spelet. `--single-attempt` återställer beteendet att stoppa efter ett försök.

**F9**,
den röda **STOP**-knappen och stängning av adapterfönstret avslutar sessionen.
Ett sådant stopp är låst: välj **Nytt försök** och armera med F8 igen. Fönstret ligger
kvar efter stopp och visar orsaken, antal giltiga bilder och rapportens sökväg.
**Stäng** avslutar programmet. Standardgränsen för preview/run är tio minuter
(probe: 60 sekunder); ändra med `--seconds`.

En separat kontrolltråd släpper adapterns hållna tangent vid fokusförlust,
F9 eller mer än 350 ms utan uppdatering. Fokusförlust, ändrad fönsterstorlek
under en aktiverad session, bildgap över 250 ms och tvetydig kubdetektion
stoppar hela sessionen och kan inte återaktiveras automatiskt.
Tangentrelease är den enda inmatning som får skickas efter fokusförlust.
Preview skickar aldrig inmatning och probe gör fortfarande högst ett hopp.
Automatisk fortsättning använder den sparade modellen; den uppdaterar inga vikter.

Verifierat i Steam 2026-10-11: en 45-sekunders session i början av Stereo Madness
gjorde **nio försök, varav åtta automatiska återupptagningar**, utan nya F8-tryck.
Loggen innehöll 668 giltiga bilder, 501 styrda bilder och 43 hopptryck med lika
många släpp. Tidsgränsen avslutade sessionen med tangenten släppt. Tester täcker
också att F9, STOP och fokusförlust aldrig kan återaktiveras av en ny spelbild.
Detta verifierar upprepade försök, inte att modellen klarar hela banan.

`--headless` tar bort det lokala fönstret; F9 och Ctrl+C finns kvar.
`--arm-after SEKUNDER` är ett uttryckligt alternativ till manuell armering för
korta tester. Använd `--output` med en ny katalog för varje session.
`frames.jsonl` innehåller observationer, tider, modellbeslut och fel;
`summary.json` anger bland annat stopporsak och om tangenten släppts.
`--record-frames` sparar dessutom lokala PNG-bilder men sänker bildtakten.
Loggens `sent` betyder att kontrollern behandlade handlingen; bara ändringar
skapar Windows-händelser. Det är inte en kvittens från spelet.

## Mät och träna vidare

```powershell
.\.venv\Scripts\python.exe -m geodaish windows probe --profile runs/windows/profile.json --jump-key up --local-only --output runs/jump-1
.\.venv\Scripts\python.exe -m geodaish windows measure --log runs/jump-1/frames.jsonl --output runs/geometry-physics.json
```

Armera med F8 på en fri startsträcka. Probe väntar på en markstående kub och
minst sex spelenheter till första synliga spiken, gör ett enda hopp och stoppar
efter landning. Mätaren kräver minst sex luftburna bilder och en bekräftad
landning; den vägrar skapa en fysikprofil från ett döds-/spårningsavbrott.

Det första provet uppskattade hastighet **8,46**, gravitation **81,27**, hoppimpuls
**16,86** och flygtid **0,415 s**, i simulatorns enheter där kuben är 0,8 bred.
Första synliga rörelse kom cirka **90 ms efter skickat tangenttryck**;
bildfångst + detektion + leverans tog median **62 ms**. Detta är grova
bildbaserade uppskattningar från en dator och ett hopp, inte exakta spelkonstanter.
Profilens åtta fördröjningssteg approximerar kedjan vid 60 Hz. Den reproducerar
inte den verkliga beslutstakten på cirka 16 Hz eller dess variationer.

```powershell
.\.venv\Scripts\python.exe -m geodaish train --resume models/demo-normal.zip --level test --observations state --physics-profile runs/geometry-physics.json --steps 20000 --envs 1 --eval-every 5000 --output runs/adapted
.\.venv\Scripts\python.exe -m geodaish evaluate --model runs/adapted/best.zip --level test --observations pixels --physics-profile runs/geometry-physics.json --episodes 1
.\.venv\Scripts\python.exe -m geodaish windows run --profile runs/windows/profile.json --model runs/adapted/best.zip --jump-key up --local-only
```

Träna snabbt med `state`, kontrollera sedan med `pixels` och sist i originalet.
Den fasta testbanan har fyra separata spikar och är bara ett integrationstest.
Nästa steg för bättre träning är flera uppmätta hopp, varierad fysik/fördröjning
och separata slumpade testbanor. Blocks, portaler, flygning, ändrad gravitation
och kamerahöjd kräver mer detektion och ett bredare observations-/handlingsformat.

## Publicera dashboarden på Vercel

1. Importera `oskar-cloud/Geodaish`, repots rot, Framework **Other**.
2. Build: `npm run build`. Output: `dist`. Inställningarna finns i `vercel.json`.
3. Anslut **Upstash Redis** via Marketplace. Sätt `UPSTASH_REDIS_REST_URL` och
   `UPSTASH_REDIS_REST_TOKEN` (äldre `KV_REST_API_URL/TOKEN` stöds också).
4. Skapa en egen slumpmässig hemlighet med minst 32 tecken som
   `TRAINING_API_TOKEN` på Vercel. Gör en ny deployment.
5. Öppna **Geometry Dash live** i sidomenyn, eller `/windows.html`.

Se [Vercels Redis-guide](https://vercel.com/docs/redis) och
[Upstash REST API](https://upstash.com/docs/redis/features/restapi).
Vercel lagrar senaste rapporten i Redis; funktionernas lokala disk används inte.
Träning och Steam-körning har separata lagringsnycklar. Båda API:erna kräver
rapporteringsnyckeln för skrivning och avvisar för gamla sekvenser.

I PowerShell på speldatorn, ange din produktionsadress och samma hemlighet
(den dolda inmatningen kräver PowerShell 7):

```powershell
$env:GEODAISH_DASHBOARD_URL = "https://ditt-projekt.vercel.app"
$env:GEODAISH_DASHBOARD_TOKEN = Read-Host "Rapporteringsnyckel" -MaskInput
.\.venv\Scripts\python.exe -m geodaish windows run --profile runs/windows/profile.json --model models/demo-normal.zip --jump-key up
```

Vyn visar då en schematisk bild av **verkligt detekterade objekt**, modellens
handling och lokal status. För beskurna spelbilder, lägg till `--stream-frames`.
Bilder publiceras endast med den flaggan. Beskärningen tar området från strax
vänster om kuben och framåt; stäng privata överlägg även där. Alla som når
webbplatsen kan läsa rapporterna och eventuella spelbilder. Hemligheten ska aldrig
läggas i Git eller frontendkod.

Rapporter skickas normalt en gång per sekund (`--report-every`) och sidan
hämtar dem varannan sekund. Det är **ögonblicksbilder, inte en videoström**.
Efter sex sekunder utan rapport blir en aktiv körning märkt `KONTAKT SAKNAS`.
Stoppade sessioner märks `STOPPAD`. Nätfel påverkar inte tangentstyrningen;
uppladdning sker i en separat tråd med bara senaste rapporten i kön.
Vercel/Redis behöver vara konfigurerade och datorn måste köra adaptern för live.
Enbart en Git-push ger webbsidan, men ingen kontakt med Steam.

För enbart lokal visning, kör `npm run dev` och öppna
`http://127.0.0.1:5173/windows.html`. Lägg till **`--local-only`** i adapterkommandot
för att garantera att inga uppladdningar sker, även om miljövariabler är satta.
Om två adapterprocesser körs samtidigt kan de konkurrera om tangenten/rapporten;
kör en adapter åt gången.

## Om programmet stänger sig eller inte hoppar

En rättning 2026-10-11 hanterar tillfälligt låsta rapportfiler på Windows.
Tidigare kunde `WinError 5 / Access is denied` vid byte av `windows-live.json`
avsluta hela adaptern. Nu behålls den senaste kompletta rapporten och nästa
publicering försöker igen utan att stoppa styrningen. Webbsidan kan under tiden
visa en äldre rapport eller kontakt saknas.

I samma felsökning hade spelets klientyta ändrats från 1480×833 till 1285×723.
Den gamla profilen gav noll giltiga bilder. Proportionell skalning är nu testad
mot den mindre spelbilden: 102 giltiga bilder, 64 styrda bilder och fem
hopptryck. Sessionen stoppade vid block som saknar stöd, och hoppknappen släpptes.
Det är ett test av skärmläsning/styrning, ingen klarad hel bana.

Stoppfönstret och knappen **Nytt försök** har kontrollerats i Windows. Ett nytt
försök får en separat rapport och kräver ny armering. F8 aktiverar inte modellen
förrän kub, mark och rörelse har kunnat läsas tillförlitligt.
