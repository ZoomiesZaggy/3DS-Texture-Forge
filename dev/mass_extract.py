"""Mass extraction of textures from a full 3DS ROM library.

Run: python dev/mass_extract.py
"""

import subprocess
import sys
import os
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROM_BASE = Path(r"D:\3ds Rom set\No-Intro\Nintendo - Nintendo 3DS (Decrypted)")
OUT_BASE = Path(r"C:\3ds-textures")
RESULTS_FILE = OUT_BASE / "_RESULTS.txt"
FAILURES_FILE = OUT_BASE / "_FAILURES.txt"
JSON_FILE = OUT_BASE / "_RESULTS.json"
MAIN = Path(r"C:\claude\3ds-tex-extract\main.py")
MAX_WORKERS = 4
TIMEOUT = 600  # 10 minutes per game

GAMES = [
    "7th Dragon III Code - VFD (USA).3ds",
    "50 Classic Games 3D (USA) (En,Fr,Es).3ds",
    "Ace Combat - Assault Horizon Legacy+ (USA) (En,Fr,Es).3ds",
    "Adventure Time - Explore the Dungeon Because I Don't Know! (USA).3ds",
    "Adventure Time - Finn & Jake Investigations (USA).3ds",
    "Adventure Time - Hey Ice King! Why'd You Steal Our Garbage!! (USA) (Rev 1).3ds",
    "Adventure Time - The Secret of the Nameless Kingdom (USA).3ds",
    "Adventures of Tintin, The - The Game (USA) (En,Fr,Es,Pt).3ds",
    "Alien Chaos 3D (USA).3ds",
    "Alliance Alive, The (USA).3ds",
    "Amazing Spider-Man 2, The (USA).3ds",
    "Amazing Spider-Man, The (USA) (En,Fr,Es).3ds",
    "American Mensa Academy (USA).3ds",
    "Andro Dunos 2 (USA).3ds",
    "Angry Birds Star Wars (USA) (En,Fr,Es,Pt).3ds",
    "Angry Birds Trilogy (USA) (En,Fr).3ds",
    "Animal Crossing - Happy Home Designer (USA) (En,Fr,Es) (Rev 1).3ds",
    "Animal Crossing - New Leaf - Welcome Amiibo (USA).3ds",
    "Animal Crossing - New Leaf (USA) (En,Fr,Es).3ds",
    "Are You Smarter than a 5th Grader (USA).3ds",
    "Art Academy - Lessons for Everyone! (USA) (En,Fr,Es).3ds",
    "Asphalt 3D (USA) (En,Fr,Es).3ds",
    "Atooi Collection (USA).3ds",
    "Azure Striker Gunvolt - Striker Pack (USA).3ds",
    "Barbie - Groom and Glam Pups (USA) (En,Fr,Es).3ds",
    "Barbie & Her Sisters - Puppy Rescue (USA).3ds",
    "Barbie Dreamhouse Party (USA) (En,Fr,Es).3ds",
    "Batman - Arkham Origins Blackgate (USA) (En,Fr,Es).3ds",
    "Battleship (USA) (En,Fr).3ds",
    "Ben 10 - Galactic Racing (USA) (En,Fr,Es).3ds",
    "Ben 10 - Omniverse 2 (USA) (En,Fr,Es).3ds",
    "Beyblade Evolution (USA) (En,Fr,Es).3ds",
    "Big Hero 6 - Battle in the Bay (USA).3ds",
    "Bit.Trip Saga (USA).3ds",
    "Blazblue - Continuum Shift II (USA) (En,Ja,Zh,Ko) (Rev 1).3ds",
    "Boulder Dash-XL 3D (USA).3ds",
    "Brain Age - Concentration Training (USA) (En,Fr,Es).3ds",
    "Bratz - Fashion Boutique (USA).3ds",
    "Bravely Default (USA) (En,Ja,Fr,De,Es,It).3ds",
    "Bravely Second - End Layer (USA) (En,Fr,Es).3ds",
    "Brunswick Pro Bowling (USA).3ds",
    "Bust-A-Move Universe (USA) (En,Fr,Es).3ds",
    "Captain America - Super Soldier (USA) (En,Fr,Es).3ds",
    "Captain Toad - Treasure Tracker (USA) (En,Fr,Es).3ds",
    "Carnival Games - Wild West 3D (USA) (En,Fr,Es).3ds",
    "Cars 2 (USA) (En,Fr,Es).3ds",
    "Cartoon Network - Battle Crashers (USA).3ds",
    "Cartoon Network - Punch Time Explosion (USA).3ds",
    "Castlevania - Lords of Shadow - Mirror of Fate (USA) (En,Fr,Es).3ds",
    "Cave Story 3D (USA).3ds",
    "Centipede - Infestation (USA) (En,Fr,Es).3ds",
    "Chibi-Robo! Zip Lash (USA).3ds",
    "Classic Games Overload - Card & Puzzle Edition (USA).3ds",
    "Cloudy with a Chance of Meatballs 2 (USA).3ds",
    "Code Name - S.T.E.A.M. (USA).3ds",
    "Code of Princess (USA).3ds",
    "Combat of Giants - Dinosaurs 3D (USA) (En,Fr,Es).3ds",
    "Conception II - Children of the Seven Stars (USA).3ds",
    "Cooking Mama - Sweet Shop (USA).3ds",
    "Cooking Mama 5 - Bon Appetit! (USA).3ds",
    "Corpse Party (USA).3ds",
    "Crash City Mayhem (USA).3ds",
    "Croods, The - Prehistoric Party! (USA) (En,Fr,Es).3ds",
    "Crosswords Plus (USA).3ds",
    "Crush 3D (USA) (En,Fr,Es).3ds",
    "Cubic Ninja (USA) (En,Fr,Es).3ds",
    "Culdcept Revolt (USA).3ds",
    "Cut the Rope - Triple Treat (USA) (En,Fr).3ds",
    "Dead or Alive - Dimensions (USA) (En,Ja,Fr,De,Es,It).3ds",
    "Deca Sports Extreme (USA) (En,Fr,Es).3ds",
    "Deer Drive Legends (USA) (En,Fr,Es).3ds",
    "Detective Pikachu (USA) (En,Ja,Fr,De,Es,It,Zh).3ds",
    "Disney Art Academy (USA).3ds",
    "Disney Epic Mickey - Power of Illusion (USA) (En,Fr,Es,Pt).3ds",
    "Disney Frozen - Olaf's Quest (USA).3ds",
    "Disney Infinity - Toy Box Challenge (USA) (En,Fr,Es,Pt).3ds",
    "Disney Magical World 2 (USA).3ds",
    "Disney Planes - Fire & Rescue (USA) (En,Fr,Es,Pt).3ds",
    "Disney Princess - My Fairytale Adventure (USA) (En,Fr,Es).3ds",
    "Disney Violetta - Rhythm & Music (USA).3ds",
    "Doctor Lautrec and the Forgotten Knights (USA) (En,Fr,Es).3ds",
    "Donkey Kong Country Returns 3D (USA) (En,Fr,Es).3ds",
    "Doodle Jump Adventures (USA).3ds",
    "Dragon Ball Fusions (USA).3ds",
    "Dragon Ball Z - Extreme Butoden (USA).3ds",
    "Dragon Quest VII - Fragments of the Forgotten Past (USA).3ds",
    "Dragon Quest VIII - Journey of the Cursed King (USA).3ds",
    "Dream Trigger 3D (USA) (En,Fr,Es).3ds",
    "DreamWorks Super Star Kartz (USA) (En,Fr).3ds",
    "Driver - Renegade (USA) (En,Fr,Es).3ds",
    "DualPenSports (USA) (En,Fr).3ds",
    "Duck Dynasty (USA).3ds",
    "Etrian Mystery Dungeon (USA).3ds",
    "Etrian Odyssey 2 Untold - The Fafnir Knight (USA).3ds",
    "Etrian Odyssey IV - Legends of the Titan (USA).3ds",
    "Etrian Odyssey Nexus (USA).3ds",
    "Etrian Odyssey Untold - The Millennium Girl (USA).3ds",
    "Etrian Odyssey V - Beyond the Myth (USA).3ds",
    "Ever Oasis (USA) (En,Fr,Es).3ds",
    "F1 2011 (USA) (En,Fr,Es).3ds",
    "Face Racers - Photo Finish (USA).3ds",
    "Fantasy Life (USA).3ds",
    "Farming Simulator 18 (USA).3ds",
    "Fast & Furious - Showdown (USA) (En,Fr).3ds",
    "FIFA 15 - Legacy Edition (USA) (En,Fr,Es).3ds",
    "Final Fantasy Explorers (USA).3ds",
    "Finding Nemo - Escape to the Big Blue - Special Edition (USA).3ds",
    "Fire Emblem - Awakening (USA).3ds",
    "Fire Emblem Echoes - Shadows of Valentia (USA) (En,Fr,Es).3ds",
    "Fire Emblem Fates - Special Edition (USA).3ds",
    "Fossil Fighters - Frontier (USA) (Rev 1).3ds",
    "Fragrant Story (USA).3ds",
    "Freakyforms Deluxe - Your Creations, Alive! (USA) (En,Fr,Es).3ds",
    "Frogger 3D (USA) (En,Fr,Es).3ds",
    "Funky Barn 3D (USA) (En,Fr,Es).3ds",
    "Gabrielle's Ghostly Groove 3D (USA).3ds",
    "Gardening Mama 2 - Forest Friends (USA).3ds",
    "Garfield Kart (USA).3ds",
    "Gem Smashers (USA).3ds",
    "Generator Rex - Agent of Providence (USA) (En,Fr).3ds",
    "Girls' Fashion Shoot (USA).3ds",
    "Go! Go! Kokopolo 3D - Space Recipe For Disaster (USA).3ds",
    "Goosebumps - The Game (USA).3ds",
    "Gravity Falls - Legend of the Gnome Gemulets (USA).3ds",
    "Green Lantern - Rise of the Manhunters (USA) (En,Fr,Es).3ds",
    "Hakuoki - Memories of the Shinsengumi (USA).3ds",
    "Happy Feet Two (USA) (En,Fr,De,Es,It,Nl).3ds",
    "Harvest Moon - Skytree Village (USA).3ds",
    "Harvest Moon 3D - A New Beginning (USA).3ds",
    "Harvest Moon 3D - The Lost Valley (USA).3ds",
    "Harvest Moon 3D - The Tale of Two Towns (USA) (Rev 2).3ds",
    "Hatsune Miku - Project Mirai DX (USA).3ds",
    "Heavy Fire - The Chosen Few 3D (USA).3ds",
    "Hello Kitty and Sanrio Friends 3D Racing (USA).3ds",
    "Hello Kitty Picnic with Sanrio Friends (USA) (Rev 1).3ds",
    "Heroes of Ruin (USA) (En,Fr,Es).3ds",
    "Hey! Pikmin (USA).3ds",
    "Hidden, The (USA).3ds",
    "Hometown Story (USA).3ds",
    "Horses 3D (USA) (En,Fr,Es).3ds",
    "Hot Wheels - World's Best Driver (USA) (En,Fr,Es).3ds",
    "Hotel Transylvania (USA) (Rev 1).3ds",
    "How to Train Your Dragon 2 (USA) (En,Fr,Es,Pt).3ds",
    "Hyrule Warriors Legends (USA).3ds",
    "Ice Age - Continental Drift - Arctic Games (USA) (En,Fr).3ds",
    "Imagine - Fashion Life (USA) (En,Fr,Es).3ds",
    "Jake Hunter Detective Story - Ghost of the Dusk (USA).3ds",
    "James Noir's Hollywood Crimes (USA) (En,Fr,Es).3ds",
    "Jaws - Ultimate Predator (USA).3ds",
    "Junior Classic Games 3D (USA) (En,Fr,Es).3ds",
    "Kid Icarus - Uprising (USA) (En,Fr,Es).3ds",
    "Kingdom Hearts 3D - Dream Drop Distance (USA) (En,Fr).3ds",
    "Kirby - Planet Robobot (USA).3ds",
    "Kirby - Triple Deluxe (USA) (En,Fr,Es).3ds",
    "Kirby Battle Royale (USA) (En,Ja,Fr,De,Es,It,Nl,Ko) (Rev 2).3ds",
    "Kirby's Extra Epic Yarn (USA) (En,Fr,Es).3ds",
    "Kung Fu Panda - Showdown of Legendary Legends (USA).3ds",
    "Lalaloopsy - Carnival of Friends (USA).3ds",
    "Langrisser Re-Incarnation - Tensei (USA).3ds",
    "Layton's Mystery Journey - Katrielle and the Millionaires' Conspiracy (USA) (En,Fr,Es).3ds",
    "LBX - Little Battlers eXperience (USA) (En,Fr,Es).3ds",
    "Legend of Korra, The - A New Era Begins (USA).3ds",
    "Legend of Legacy, The (USA).3ds",
    "Legend of Zelda, The - A Link Between Worlds (USA) (En,Fr,Es).3ds",
    "Legend of Zelda, The - Majora's Mask 3D (USA) (En,Fr,Es) (Rev 1).3ds",
    "Legend of Zelda, The - Ocarina of Time 3D (USA) (En,Fr,Es) (Rev 1).3ds",
    "Legend of Zelda, The - Tri Force Heroes (USA) (En,Fr,Es).3ds",
    "Legends of Oz - Dorothy's Return (USA).3ds",
    "LEGO Batman 3 - Beyond Gotham (USA) (En,Fr,Es,Pt).3ds",
    "LEGO City Undercover - The Chase Begins (USA) (En,Fr,Es).3ds",
    "LEGO Friends (USA) (En,Fr,Es,Pt).3ds",
    "LEGO Harry Potter - Years 5-7 (USA) (En,Fr,Es,Pt).3ds",
    "LEGO Jurassic World (USA) (En,Fr,Es,Pt).3ds",
    "LEGO Legends of Chima - Laval's Journey (USA) (En,Fr,Es,Pt).3ds",
    "LEGO Marvel Avengers (USA) (En,Fr,Es,Pt).3ds",
    "LEGO Marvel Super Heroes - Universe in Peril (USA) (En,Fr,Es,Pt) (English-only Audio).3ds",
    "LEGO Movie Videogame, The (USA) (En,Fr,Es,Pt).3ds",
    "LEGO Ninjago - Shadow of Ronin (USA) (En,Fr,Es,Pt) (Rev 1).3ds",
    "LEGO Pirates of the Caribbean - The Video Game (USA) (En,Fr,Es) (Rev 1).3ds",
    "LEGO Star Wars - The Force Awakens (USA).3ds",
    "LEGO Star Wars III - The Clone Wars (USA) (En,Fr,Es).3ds",
    "LEGO The Hobbit (USA) (En,Fr,Es,Pt).3ds",
    "LEGO The Lord of the Rings (USA) (En,Fr,Es,Pt).3ds",
    "Lord of Magna - Maiden Heaven (USA).3ds",
    "Luigi's Mansion - Dark Moon (USA) (En,Fr,Es).3ds",
    "Luigi's Mansion (USA).3ds",
    "Madagascar 3 - The Video Game (USA) (En,Fr,Es).3ds",
    "Madden NFL Football (USA).3ds",
    "Mario & Luigi - Bowser's Inside Story + Bowser Jr.'s Journey (USA).3ds",
    "Mario & Luigi - Dream Team (USA) (En,Fr,Es) (Rev 1).3ds",
    "Mario & Luigi - Paper Jam (USA).3ds",
    "Mario & Luigi - Superstar Saga + Bowser's Minions (USA) (En,Fr,Es).3ds",
    "Mario & Sonic at the Rio 2016 Olympic Games (USA) (En,Fr,Es).3ds",
    "Mario Golf - World Tour (USA) (En,Fr,Es).3ds",
    "Mario Kart 7 (USA) (En,Fr,Es) (Rev 1).3ds",
    "Mario Party - Island Tour (USA) (En,Fr,Es).3ds",
    "Mario Party - Star Rush (USA) (En,Fr,Es).3ds",
    "Mario Party - The Top 100 (USA).3ds",
    "Mario Sports Superstars (USA).3ds",
    "Mario Tennis Open (USA) (En,Fr,Es) (Rev 1).3ds",
    "Mega Man Legacy Collection (USA).3ds",
    "Metal Gear Solid - Snake Eater 3D (USA) (En,Fr,Es).3ds",
    "Metroid - Samus Returns (USA) (En,Fr,Es).3ds",
    "Metroid Prime - Federation Force (USA) (En,Fr,Es).3ds",
    "Michael Jackson - The Experience 3D (USA) (En,Fr,Es).3ds",
    "Miitopia (USA) (En,Fr,Es).3ds",
    "Moco Moco Friends (USA).3ds",
    "Monster High - New Ghoul in School (USA).3ds",
    "Monster Hunter 3 Ultimate (USA) (En,Fr,De,Es,It).3ds",
    "Monster Hunter 4 Ultimate (USA).3ds",
    "Monster Hunter Generations (USA).3ds",
    "Monster Hunter Stories (USA).3ds",
    "Myst (USA) (En,Fr).3ds",
    "Nano Assault (USA).3ds",
    "Naruto Powerful Shippuden (USA) (En,Fr,Es).3ds",
    "Need for Speed - The Run (USA) (En,Fr,Es).3ds",
    "New Super Mario Bros. 2 (USA) (En,Fr,Es).3ds",
    "Nickelodeon Teenage Mutant Ninja Turtles (USA) (En,Fr).3ds",
    "Nintendogs + Cats - French Bulldog & New Friends (USA) (En,Fr,Es) (Rev 2).3ds",
    "Nintendogs + Cats - Golden Retriever & New Friends (USA) (En,Fr,Es) (Rev 2).3ds",
    "Nintendogs + Cats - Toy Poodle & New Friends (USA) (En,Fr,Es) (Rev 2).3ds",
    "One Piece - Romance Dawn (USA) (En,Fr,Es).3ds",
    "One Piece - Unlimited World Red (USA).3ds",
    "Pac-Man & Galaga Dimensions (USA) (En,Fr,Es).3ds",
    "Pac-Man and the Ghostly Adventures (USA) (En,Fr,Es).3ds",
    "Pac-Man and the Ghostly Adventures 2 (USA).3ds",
    "Pac-Man Party 3D (USA) (En,Fr,Es).3ds",
    "Paper Mario - Sticker Star (USA) (En,Fr,Es).3ds",
    "Peanuts Movie, The - Snoopy's Grand Adventure (USA).3ds",
    "Penguins of Madagascar (USA) (En,Fr).3ds",
    "Persona Q - Shadow of the Labyrinth (USA).3ds",
    "Persona Q2 - New Cinema Labyrinth (USA).3ds",
    "Pilotwings Resort (USA) (En,Fr,Es) (Rev 1).3ds",
    "Pokemon Alpha Sapphire (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds",
    "Pokemon Moon (USA) (En,Ja,Fr,De,Es,It,Zh,Ko).3ds",
    "Pokemon Mystery Dungeon - Gates to Infinity (USA).3ds",
    "Pokemon Omega Ruby (USA) (En,Ja,Fr,De,Es,It,Ko) (Rev 2).3ds",
    "Pokemon Rumble Blast (USA) (Rev 1).3ds",
    "Pokemon Rumble World (USA).3ds",
    "Pokemon Sun (USA) (En,Ja,Fr,De,Es,It,Zh,Ko).3ds",
    "Pokemon Super Mystery Dungeon (USA).3ds",
    "Pokemon Ultra Moon (USA) (En,Ja,Fr,De,Es,It,Zh,Ko).3ds",
    "Pokemon Ultra Sun (USA) (En,Ja,Fr,De,Es,It,Zh,Ko).3ds",
    "Pokemon X (USA) (En,Ja,Fr,De,Es,It,Ko).3ds",
    "Pokemon Y (USA) (En,Ja,Fr,De,Es,It,Ko).3ds",
    "Poochy & Yoshi's Woolly World (USA) (En,Fr,Es) (Rev 1).3ds",
    "Professor Layton and the Azran Legacy (USA).3ds",
    "Professor Layton and the Miracle Mask (USA) (Rev 1).3ds",
    "Professor Layton vs. Phoenix Wright - Ace Attorney (USA) (En,Fr,Es).3ds",
    "Project X Zone 2 (USA).3ds",
    "Puzzle & Dragons Z + Puzzle & Dragons Super Mario Bros. Edition (USA).3ds",
    "Rabbids Rumble (USA) (En,Fr,Es,Pt).3ds",
    "Radiant Historia - Perfect Chronology (USA).3ds",
    "Rayman Origins (USA) (En,Fr,Es).3ds",
    "Regular Show - Mordecai & Rigby in 8-Bit Land (USA).3ds",
    "Resident Evil - Revelations (USA) (En,Ja,Fr,De,Es,It) (Rev 1).3ds",
    "Resident Evil - The Mercenaries 3D (USA) (En,Fr) (Rev 1).3ds",
    "Return to PopoloCrois - A Story of Seasons Fairytale (USA).3ds",
    "Rhythm Thief & the Emperor's Treasure (USA) (En,Fr,Es).3ds",
    "Ridge Racer 3D (USA) (En,Fr,Es).3ds",
    "River City - Rival Showdown (USA).3ds",
    "Rodea the Sky Soldier (USA).3ds",
    "RPG Maker Fes (USA) (En,Fr,Es).3ds",
    "Rune Factory 4 (USA).3ds",
    "Samurai Warriors - Chronicles (USA).3ds",
    "Scribblenauts Unlimited (USA) (En,Fr,Es,Pt).3ds",
    "Sega 3D Classics Collection (USA).3ds",
    "Senran Kagura 2 - Deep Crimson (USA).3ds",
    "Shantae and the Pirate's Curse (USA).3ds",
    "Shin Megami Tensei - Devil Summoner - Soul Hackers (USA).3ds",
    "Shin Megami Tensei - Devil Survivor 2 - Record Breaker (USA).3ds",
    "Shin Megami Tensei - Devil Survivor Overclocked (USA) (Rev 1).3ds",
    "Shin Megami Tensei - Strange Journey Redux (USA).3ds",
    "Shin Megami Tensei IV - Apocalypse (USA).3ds",
    "Shin Megami Tensei IV (USA).3ds",
    "Shovel Knight (USA).3ds",
    "Sims 3, The (USA) (En,Fr,Es).3ds",
    "Skylanders Giants (USA) (En,Fr,Es).3ds",
    "Skylanders Swap Force (USA) (En,Fr,Es,Pt).3ds",
    "Skylanders Trap Team (USA) (En,Fr,Es,Pt).3ds",
    "Sonic & All-Stars Racing Transformed (USA) (En,Fr,Es).3ds",
    "Sonic Boom - Shattered Crystal (USA).3ds",
    "Sonic Generations (USA) (En,Fr,Es) (Rev 1).3ds",
    "Sonic Lost World (USA) (En,Fr,Es).3ds",
    "Spider-Man - Edge of Time (USA).3ds",
    "Spirit Camera - The Cursed Memoir (USA).3ds",
    "SpongeBob HeroPants (USA).3ds",
    "Star Fox 64 3D (USA) (En,Fr,Es) (Rev 3).3ds",
    "Steel Diver (USA) (En,Fr,Es).3ds",
    "Stella Glow (USA).3ds",
    "Story of Seasons - Trio of Towns (USA).3ds",
    "Story of Seasons (USA).3ds",
    "Style Savvy - Fashion Forward (USA).3ds",
    "Super Mario 3D Land (USA) (En,Fr,Es) (Rev 1).3ds",
    "Super Mario Maker for Nintendo 3DS (USA) (En,Fr,Es) (Rev 3).3ds",
    "Super Smash Bros. for Nintendo 3DS (USA) (En,Fr,Es) (Rev 11).3ds",
    "Super Street Fighter IV - 3D Edition (USA) (En,Fr,Es).3ds",
    "Sushi Striker - The Way of Sushido (USA) (En,Fr,Es).3ds",
    "Tales of the Abyss (USA).3ds",
    "Teenage Mutant Ninja Turtles - Danger of the Ooze (USA).3ds",
    "Terraria (USA) (Rev 1).3ds",
    "Theatrhythm Final Fantasy - Curtain Call (USA).3ds",
    "Tom Clancy's Ghost Recon - Shadow Wars (USA) (En,Fr,Es).3ds",
    "Tomodachi Life (USA) (Rev 1).3ds",
    "Transformers - Rise of the Dark Spark (USA) (En,Fr).3ds",
    "Transformers Prime - The Game (USA) (En,Fr).3ds",
    "Ultimate NES Remix (USA) (En,Fr,Es).3ds",
    "WarioWare Gold (USA) (Rev 1).3ds",
    "Wipeout 3 (USA).3ds",
    "WWE All Stars (USA) (En,Fr,Es).3ds",
    "Xenoblade Chronicles 3D (USA).3ds",
    "Yo-Kai Watch (USA).3ds",
    "Yo-Kai Watch 2 - Bony Spirits (USA).3ds",
    "Yo-Kai Watch 2 - Fleshy Souls (USA).3ds",
    "Yo-Kai Watch 3 (USA).3ds",
    "Yo-Kai Watch Blasters - Red Cat Corps (USA).3ds",
    "Yoshi's New Island (USA) (En,Fr,Es).3ds",
    "Zero Escape - Virtue's Last Reward (USA) (Rev 2).3ds",
    "Zero Escape - Zero Time Dilemma (USA).3ds",
]


def extract_game(rom_name):
    """Extract textures from a single ROM. Returns (rom_name, status, count, quality, note)."""
    rom_path = ROM_BASE / rom_name
    if not rom_path.exists():
        return rom_name, "MISSING", 0, 0.0, "ROM file not found"

    # Truncate folder name for filesystem safety
    game_short = rom_path.stem
    if len(game_short) > 60:
        game_short = game_short[:60]
    # Remove problematic chars
    game_short = game_short.replace("'", "").replace('"', "").replace("!", "").replace("&", "and")
    out_dir = OUT_BASE / game_short

    cmd = [
        sys.executable, str(MAIN),
        "extract", str(rom_path),
        "-o", str(out_dir),
        "--quiet",
    ]

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            cwd=str(MAIN.parent),
        )
        elapsed = time.time() - start
        output = result.stdout + result.stderr

        # Parse texture count from "Textures decoded OK:    N,NNN"
        count = 0
        for line in output.splitlines():
            if "Textures decoded OK" in line or "Textures found" in line:
                m = re.search(r'([\d,]+)', line.split(":")[1] if ":" in line else line)
                if m:
                    count = int(m.group(1).replace(",", ""))
                    break

        # Parse quality score from output or quality_report.json
        quality = 0.0
        qfile = out_dir / "quality_report.json"
        if qfile.exists():
            try:
                data = json.loads(qfile.read_text())
                quality = data.get("quality_score", 0.0)
            except Exception:
                pass
        else:
            # Try parsing from output
            for line in output.splitlines():
                if "Quality score:" in line:
                    m = re.search(r'([\d.]+)%', line)
                    if m:
                        quality = float(m.group(1)) / 100.0
                        break

        # Check for errors
        if result.returncode == 2:
            return rom_name, "ENCRYPTED", 0, 0.0, f"{elapsed:.1f}s"
        elif result.returncode != 0 and count == 0:
            err = ""
            for line in output.splitlines():
                if "ERROR" in line or "Fatal" in line:
                    err = line.strip()[:80]
                    break
            return rom_name, "ERROR", 0, 0.0, err or f"exit code {result.returncode}"

        status = "OK" if count > 0 else "ZERO"
        return rom_name, status, count, quality, f"{elapsed:.1f}s"

    except subprocess.TimeoutExpired:
        return rom_name, "TIMEOUT", 0, 0.0, f"Exceeded {TIMEOUT}s"
    except Exception as e:
        return rom_name, "ERROR", 0, 0.0, str(e)[:80]


def main():
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    start_time = datetime.now()
    print(f"{'=' * 70}")
    print(f"  3DS Texture Forge - Mass Extraction")
    print(f"  {len(GAMES)} games, {MAX_WORKERS} parallel workers")
    print(f"  Output: {OUT_BASE}")
    print(f"  Started: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}")

    results = []
    completed = 0
    total_tx = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(extract_game, g): g for g in GAMES}
        for future in as_completed(futures):
            rom, status, count, quality, note = future.result()
            completed += 1
            total_tx += count
            pct = completed / len(GAMES) * 100
            q_str = f"{quality:.0%}" if quality > 0 else " -- "
            print(f"[{completed:3d}/{len(GAMES)}] {pct:5.1f}% | {status:9s} | "
                  f"{count:8,d} tx | Q:{q_str:>4s} | {rom[:55]}")
            results.append({
                "rom": rom,
                "status": status,
                "count": count,
                "quality": round(quality, 3),
                "note": note,
            })

    end_time = datetime.now()
    elapsed_total = (end_time - start_time).total_seconds()

    # Sort by count descending
    results.sort(key=lambda x: x["count"], reverse=True)

    # Categorize
    ok = [r for r in results if r["status"] == "OK"]
    zero = [r for r in results if r["status"] == "ZERO"]
    missing = [r for r in results if r["status"] == "MISSING"]
    encrypted = [r for r in results if r["status"] == "ENCRYPTED"]
    errors = [r for r in results if r["status"] in ("ERROR", "TIMEOUT")]

    # Build summary
    lines = []
    lines.append("=" * 70)
    lines.append("  3DS Texture Forge - Mass Extraction Results")
    lines.append("=" * 70)
    lines.append(f"  Completed:   {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  Duration:    {elapsed_total / 60:.1f} minutes")
    lines.append(f"  Total games: {len(GAMES)}")
    lines.append(f"  Success:     {len(ok)} games")
    lines.append(f"  Zero tx:     {len(zero)} games")
    lines.append(f"  Missing:     {len(missing)} ROMs not found")
    lines.append(f"  Encrypted:   {len(encrypted)} ROMs encrypted")
    lines.append(f"  Errors:      {len(errors)} games crashed/timed out")
    lines.append(f"  Total textures extracted: {total_tx:,}")
    lines.append("")
    lines.append(f"ALL GAMES BY TEXTURE COUNT:")
    lines.append("-" * 70)
    for r in results:
        q = f"{r['quality']:.0%}" if r['quality'] > 0 else " -- "
        lines.append(f"  {r['status']:9s} {r['count']:8,d}  Q:{q:>4s}  {r['rom'][:55]}")

    if zero:
        lines.append("")
        lines.append(f"ZERO TEXTURE GAMES ({len(zero)}):")
        lines.append("-" * 70)
        for r in zero:
            lines.append(f"  {r['rom'][:65]}  [{r['note']}]")

    if errors:
        lines.append("")
        lines.append(f"ERRORS / TIMEOUTS ({len(errors)}):")
        lines.append("-" * 70)
        for r in errors:
            lines.append(f"  {r['rom'][:55]}  [{r['note']}]")

    if encrypted:
        lines.append("")
        lines.append(f"ENCRYPTED ROMs ({len(encrypted)}):")
        lines.append("-" * 70)
        for r in encrypted:
            lines.append(f"  {r['rom']}")

    if missing:
        lines.append("")
        lines.append(f"MISSING ROM FILES ({len(missing)}):")
        lines.append("-" * 70)
        for r in missing:
            lines.append(f"  {r['rom']}")

    summary = "\n".join(lines)
    print("\n" + summary)

    RESULTS_FILE.write_text(summary, encoding="utf-8")
    JSON_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # Write failures file
    failures = [r for r in results if r["status"] != "OK"]
    FAILURES_FILE.write_text(
        "\n".join(f"{r['status']:9s} {r['rom']}" for r in failures),
        encoding="utf-8"
    )

    print(f"\nResults saved to:")
    print(f"  {RESULTS_FILE}")
    print(f"  {JSON_FILE}")
    print(f"  {FAILURES_FILE}")


if __name__ == "__main__":
    main()
