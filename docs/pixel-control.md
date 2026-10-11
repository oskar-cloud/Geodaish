# Första steget mot bildstyrning

Kedjan fungerar nu i den egna simulatorn:

**RGB-bild → kub och spikar → rörelse mellan bilder → PPO → håll/släpp hopp.**

`--observations pixels` ger modellen samma 16 normaliserade tal som tidigare,
men räknar fram dem från bilder. Det är färg- och geometribaserad bildtolkning
före PPO, inte ett nytt neuralt bildnätverk. Belöning, kollisioner och avslut
kommer fortfarande från simulatorn. Utan flaggan används exakta speldata.

## Kör testbanan

På Windows, från projektmappen efter installation:

```powershell
.\.venv\Scripts\python.exe -m geodaish watch --model models/demo-normal.zip --observations pixels --level test
```

I en aktiverad Python-miljö på andra system:

```bash
geodaish watch --model models/demo-normal.zip --observations pixels --level test
```

Testbanan är platt och har fyra separata spikar, på positionerna 8, 16, 24 och
32. Gula ramar visar vilka objekt bildtolkningen hittat. **R** startar om och
**Escape** stänger. Modellens `0/1` släpper/håller simulatorns hoppknapp, samma
handling som mellanslag använder vid `play`. Inga globala tangenttryck skickas.

Kör utan fönster och spara ett jämförbart resultat:

```bash
geodaish evaluate --model models/demo-normal.zip --observations pixels --level test --episodes 1 --output runs/pixel-evaluation.json
```

Rapporten jämför modellen med slumpmässiga hopp och en handkodad referens.
Flera försök på `--level test` upprepar **samma bana**, även om seed ändras.
Det testar integrationen; det är inte ett generaliseringstest. Använd
`--level generated` och separata seeds för senare utvärdering på nya banor.

I [det första sparade testet](pixel-results.json) klarade demomodellen alla fyra
spikar med bildobservationer och utan extra inmatningsfördröjning. Med den
kalibrerade profilen och två bildrutors fördröjning nådde modellen ungefär 40 %,
även efter 4 096 steg finjustering. Stödet för träning är verifierat; den korta
finjusteringen gav ännu ingen modell som klarar hela den fördröjda banan.

## Mät hopp och fördröjning

```bash
geodaish calibrate --input-delay 2 --output runs/pixel-calibration.json
```

Kalibreringen gör ett isolerat hopp på en fri startsträcka. Höjd och horisontell
rörelse mäts från bildrutor. En parabel anpassas till hoppet för att uppskatta
gravitation och hopphastighet, med korrigering för simulatorns två fysikdelsteg.
Rapporten innehåller råa mätpunkter och en återanvändbar `training`-profil.

Det finns tre separata tidsmått:

- **Inmatningskö:** antal hela bildrutor mellan beslut och levererad handling.
  Både tryck och släpp fördröjs; kön töms vid omstart. `0–30` stöds.
- **Beslut till synlig rörelse:** inmatningskön plus första fysiksteget, med
  en bildrutas tidsupplösning. Två fördröjda bildrutor ger normalt 50 ms vid 60 Hz.
- **Bearbetning på datorn:** faktisk tid för rendering/bildtolkning i
  kalibreringen och rendering/bildtolkning/modellbeslut i utvärderingen.
  Denna väggklockstid läggs inte automatiskt till simulatorns inmatningskö.

Mätningen gäller Geodaish. Den mäter inte originalspelets skärmfångst,
operativsystemets tangentleverans eller en verklig skärms fördröjning.

## Anpassa träningen

```bash
geodaish train --observations pixels --level test --physics-profile runs/pixel-calibration.json --resume models/demo-normal.zip --steps 20000 --envs 1 --output runs/pixel-adaptation
```

Ange en ny utdatakatalog. Kalibreringens hastighet, gravitation, hoppimpuls och
inmatningskö används av träning, validering och dashboardens modelluppspelning.
De upplösta inställningarna sparas i körningens `config.json`. En explicit
`--input-delay` ersätter fördröjningen i profilen. Ändrad fysik kan göra en bana
omöjlig; kontrollera hoppen innan ett längre träningspass.

Använd samma inställningar när du testar den nya modellen:

```bash
geodaish evaluate --model runs/pixel-adaptation/best.zip --observations pixels --level test --physics-profile runs/pixel-calibration.json --episodes 1
geodaish watch --model runs/pixel-adaptation/best.zip --observations pixels --level test --physics-profile runs/pixel-calibration.json
```

Pixelträning renderar och analyserar varje bild och är därför långsammare än
träning med exakta speldata. En lyckad körning med den gamla modellen räcker
inte som bevis för att träningen är anpassad till en annan fysik eller latens.

## Gränsen för detta steg

Bildtolkningen är kalibrerad för Geodaishs egen grafik: grön kub och marklinje,
rosa spikar, 68 pixlar per spelenhet och spelområdet under HUD:en vid y=150.
Den känner bara till synliga spikar. Kamerans kortare synfält kan därför ge
färre hinder än simulatorns exakta observationer. Hastighet kräver minst två
bilder; vid start är den okänd (noll), och mellan synliga hinder behålls senaste
uppskattningen. Borttappad kub eller mark ger ett tydligt fel och stoppar loopen.
Terminalbilder används inte till fler modellbeslut.

Originalspelet har nu en separat [Windows-adapter](windows-adapter.md) med
skärmläsning, kalibrerad detektion, hoppstyrning och stoppfunktion. Där finns
också en separat mätning från Steam-spelet. Resultaten ovan gäller fortsatt
Geodaishs egen simulator.
