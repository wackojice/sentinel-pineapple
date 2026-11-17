# Sentinel

Un module pour le WiFi Pineapple Mark VII qui surveille ton propre Wi-Fi au lieu d'attaquer celui des autres.

[English version](README.md)

![Onglet Overview](docs/screenshots/1-overview.png)

J'avais un Pineapple qui traînait dans un tiroir. Une fois tes tests finis, il n'y a plus grand-chose à faire avec,
et je me suis dit que je ne devais pas être le seul dans ce cas. Alors j'ai transformé le mien en outil utile à la
maison : il écoute le Wi-Fi autour, me dit à quel point mes réseaux sont sécurisés, et m'avertit si quelque chose de
louche apparaît, comme quelqu'un qui copie le nom de mon réseau ou qui déconnecte mes appareils.

Sentinel ne fait qu'écouter. Il n'envoie rien et n'attaque rien. Par défaut, il ne garde aucune info sur les
appareils des autres non plus.

## Ce qu'il te signale

| Alerte | Ce qui s'est passé |
|---|---|
| Imitation de ton réseau | Une autre borne utilise le nom de ton réseau. Critique si sa sécurité est plus faible que la tienne. |
| Deux appareils, une adresse | L'adresse de ta borne apparaît avec deux réglages différents en même temps. |
| Sécurité plus faible | Ta borne annonce soudain une sécurité plus faible, ou n'exige plus le PMF. |
| Borne modifiée | Son empreinte a changé. Souvent une mise à jour ; tu peux accepter le nouvel état en un clic. |
| Changement de canal | Ta borne est passée sur un canal qu'elle n'utilise pas d'habitude. |
| Rafale de désauthentifications | 10 trames en 5 secondes, ou 30 en une minute, sur la même borne. |
| Faux points d'accès | Des dizaines de bornes jamais vues, toutes en même temps. |
| Répond à tous les noms | Une borne annonce 5 noms différents en une minute. |

![Onglet Detection](docs/screenshots/5-detection.png)

À garder en tête : les radios sautent d'un canal à l'autre, donc chaque canal n'est écouté qu'une partie du temps.
Une attaque très courte peut passer. Sentinel te dit ce qu'il voit, il ne bloque rien.

## Ce qu'il te faut

- Un WiFi Pineapple Mark VII (testé avec le firmware 2.1.3)
- L'adaptateur MK7AC si tu veux aussi le 5 GHz (canaux DFS compris). Sans lui, tu as seulement le 2,4 GHz.
- Un ordinateur branché au Pineapple. Le Pineapple n'a pas besoin d'Internet.

## Installation

Télécharge tous les fichiers de la [dernière version](../../releases/latest) dans un même dossier. Ensuite, depuis
ce dossier sur ton ordinateur :

```sh
sha256sum -c SHA256SUMS          # sur Mac : shasum -a 256 -c SHA256SUMS
sh install-from-pc.sh --reboot   # il va demander le mot de passe root du Pineapple
```

Le script copie tout sur le Pineapple, installe le module et `python3-sqlite3` (la seule chose qui manque au
firmware d'origine), puis le redémarre. Quand il est revenu, recharge la page du Pineapple avec Ctrl+Maj+R et ouvre
Sentinel. Les autres façons d'installer sont dans la [version anglaise](README.md#install).

## Pour commencer

Dans **Settings**, la Radio 1 est `wlan1mon` (2,4 GHz). Active la Radio 2, choisis `wlan3` (le MK7AC) et clique sur
« 5 GHz, all channels ». Enregistre, puis clique sur Start monitoring.

Va ensuite dans **Security** et dis-lui quels réseaux sont à toi. Tape le nom de ton réseau dans la recherche et
clique sur l'étoile en haut de la liste. Toutes les bornes qui portent ce nom sont marquées. Si tu as plusieurs
bornes, il va aussi te proposer les autres réseaux qu'elles diffusent. À partir de là, tu as un score pour tes
propres réseaux, et la détection sait quoi surveiller.

![Onglet Security](docs/screenshots/3-security.png)

Après ça, laisse-le tourner. Les alertes s'affichent dans **Detection**, avec un compteur sur l'onglet.

## Bon à savoir

- Les adresses des appareils et les noms de réseaux que cherchent les téléphones ne sont pas enregistrés, sauf si tu
  l'actives dans Settings.
- Il utilise environ 40 % du processeur du Pineapple avec les deux radios, environ 12 Mo de mémoire, et la base ne
  dépasse jamais 64 Mo.
- Pendant qu'il tourne, Sentinel coupe `wlan3` (le MK7AC en mode normal) pour que la radio 5 GHz puisse changer de
  canal. L'arrêter, redémarrer ou désinstaller le remet.
- Ne lance pas Recon sur la même radio en même temps. Si tu as besoin du Pineapple pour autre chose, arrête juste
  l'écoute.
- Au Canada, les canaux 120 à 128 sont réservés aux radars météo. Le module les saute, c'est normal.
- Le Pineapple n'a pas de pile pour son horloge, donc l'heure dérive après un redémarrage. Sentinel calcule les
  durées avec l'horloge du Pineapple pour que « il y a 5 min » reste juste.

## Désinstallation

```sh
sh /pineapple/modules/Sentinel/uninstall.sh            # garde tes données et python3-sqlite3
sh /pineapple/modules/Sentinel/uninstall.sh --purge    # efface aussi /root/.Sentinel
```

Licence MIT. Fait par Not_Hackerman, avec l'aide de Claude et Fable. Les captures viennent de la démo, les noms de
réseaux qu'on y voit sont inventés.
