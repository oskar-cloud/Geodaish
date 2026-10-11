# Demomodell: normal

`demo-normal.zip` är en PPO-modell som faktiskt har tränats i `DashEnv`. Den
handkodade referensen användes inte för att välja hopp eller uppdatera modellen.

Kör från projektets rot med den aktiverade Python-miljön:

```bash
geodaish watch --model models/demo-normal.zip
geodaish evaluate --model models/demo-normal.zip --episodes 100
```

Träningen gjordes på CPU på en MacBook Neo, Apple A18 Pro, 8 GB RAM:

```bash
geodaish train --steps 300000 --output runs/first-normal --seed 42
geodaish train --resume runs/first-normal/best.zip --steps 2000000 --output runs/normal-continued --seed 43 --eval-every 100000
```

Första körningen tog 18,3 sekunder och den fortsatta 125,3 sekunder, inklusive
återkommande validering. Återupptagningen startade från den första körningens
bästa checkpoint vid 120 000 steg. Modellvalet gjordes efter medelbelöning på tio
valideringsbanor (seeds 10000–10009). Den valda modellen ligger vid 1 920 004
kumulativa miljösteg. `demo-normal.json` innehåller maskinläsbar metadata och
SHA-256 för modellen. Tiderna är observationer från denna dator, inte garantier.

Efter modellvalet kördes ett separat sluttest på 100 banor, seeds 20000–20099:

| Agent | Klarade banor | Genomsnittligt framsteg |
|---|---:|---:|
| PPO | 100 / 100 | 100 % |
| Slumpmässiga hopp | 0 / 100 | 12,3 % |
| Handkodad referens | 100 / 100 | 100 % |

Fullständiga episodresultat: [`evaluation-normal.json`](../docs/evaluation-normal.json).
En modell och 100 banor räcker inte för att dra slutsatser om alla seeds,
svårighetsgrader eller det riktiga Geometry Dash.
