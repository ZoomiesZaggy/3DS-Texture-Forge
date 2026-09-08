"""Top-level extraction orchestration.

Module layout:

    extractor.py     -- ExtractionPipeline (the entry point)
    scanner.py       -- classify_file + dispatch helper
    filter.py        -- FileFilter: which RomFS files even to peek at
    dedup.py         -- Deduper (xxhash raw + md5 decoded)
    adapters.py      -- per-game / paired-file tweaks (Smash dt/ls, Star Fox
                        GDB1 pairs, Pokemon PC sections, GARC bch suppression)
    progress.py      -- ProgressCallback ABC for CLI bar / GUI signals
    raw_heuristic.py -- last-resort raw texture guess
"""
