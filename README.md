<html>
<body>
<!--StartFragment--><html><head></head><body><h1>3DS Texture Forge: v1.0-beta Release Report</h1>
<p><strong>by ZoomiesZaggy · March 2026</strong></p>
<hr>
<blockquote>
<p><strong>A note on how this was built:</strong> This tool was developed entirely with Claude (Anthropic's AI assistant). Weeks of diligent prompting, oversight, and iteration. Not a weekend vibe-coding session. I want to be upfront about that because the community has complicated feelings about AI, and those feelings are valid. My position: AI writing code is a tool, the same way a compiler is a tool. AI generating art is a different conversation, one I personally land on the opposite side of. Which is exactly why this tool exists. It extracts raw source textures from 3DS ROMs so that artists, modders, and preservationists can do the painstaking, skilled, human work of redrawing, remastering, and reimagining them properly. <strong>The extraction is automated. The artistry is yours.</strong></p>
</blockquote>
<hr>
<h2>Why this exists</h2>
<p>The AYN Thor changed things. A handheld powerful enough to run Azahar at full speed, in a clamshell form factor (two screens, the way Nintendo intended) finally made 3DS games feel like a platform worth investing in again rather than a museum piece. And Azahar's custom texture support means you can actually do something with that hardware: replace the original 240p assets with hand-crafted high-resolution replacements and experience games like Ocarina of Time 3D, Fire Emblem Awakening, or Pokémon X the way they were always trying to look, constrained only by a 2011 GPU.</p>
<p>The problem is that getting those original textures out of a ROM was either impossible, broken, or required stitching together three different tools none of which agreed on format. 3DS Texture Forge exists to fix that. Drop in a decrypted ROM, get a folder of PNGs. That's it.</p>
<hr>
<h2>What v1.0-beta can do</h2>

Metric | Value
-- | --
Games supported | 180+
Textures extracted (full library run) | 1,527,047
Average quality score | ~97%
Parsers implemented | 25+


<hr>
<h2>Known limitations: read this before filing a bug</h2>
<blockquote>
<p><strong>This is a beta. Broken and missing textures are expected.</strong> If a game you care about has issues, that's useful signal, but please check below before assuming it's a bug.</p>
</blockquote>
<h3>Unsupported games</h3>
<p>These formats require executable reverse engineering to crack and are out of scope for this tool:</p>
<ul>
<li><strong>All 15 LEGO 3DS titles:</strong> TT Games uses a proprietary streaming compression format (FUSE) that would require disassembling the game executable to reverse engineer.</li>
<li><strong>Ghost Recon: Shadow Wars and other Ubisoft 3DS titles:</strong> Ubisoft's MAGM engine leaves nothing recognizable in the ROM. Confirmed dead end.</li>
<li><strong>Various EA and Activision titles:</strong> fully proprietary engines, no standard texture containers present.</li>
</ul>
<h3>Partially supported games</h3>
<ul>
<li><strong>Luigi's Mansion: Dark Moon:</strong> 869 textures accessible via deep scan (<code>--scan-all</code> flag) but the normal pipeline misses them. Next Level Games' container format isn't fully parsed.</li>
<li><strong>Yo-Kai Watch series:</strong> IMGC format is decoded but the Huffman compression has edge cases that produce tile artifacts in some textures. Quality sits around 80% instead of 95%+.</li>
<li><strong>Professor Layton: Azran Legacy:</strong> similar Huffman edge case issue, some textures show glitch blocks.</li>
<li><strong>RE: Mercenaries 3D:</strong> only ~155 textures extracted vs the expected ~1,300+. Same Capcom engine as Revelations but a different internal layout variant not yet handled.</li>
</ul>
<h3>Thin-strip textures</h3>
<p>You'll see some textures with dimensions like 512x8 or 256x8. These come from BCH files where the GPU command parser finds no dimension data and the fallback heuristic guesses wrong. The pixel data exists but the dimensions are misread. These are flagged in the quality report.</p>
<h3>Encrypted ROMs</h3>
<p>The tool requires <strong>decrypted ROMs</strong>. Use GodMode9 on a hacked 3DS to dump and decrypt your cartridges. Encrypted dumps will produce zero textures. That's not a bug, that's DRM.</p>
<h3>Quality score interpretation</h3>
<p>A quality score of 93% doesn't mean 7% of textures are broken. It means 7% triggered a heuristic flag: solid color, low variance, very dark or very bright. Many of those are legitimate: shadow maps, palette swatches, gradient fills, tiny UI elements. The score is a starting point for investigation, not a verdict.</p>
<hr>
<h2>What this tool is for</h2>
<p>To be direct: this tool extracts raw source assets so that human artists can work with them. The intended workflow for an Azahar texture pack (on your AYN Thor, your Steam Deck, your PC) is:</p>
<ol>
<li>Extract textures with this tool</li>
<li>Use the originals as reference and scale guides</li>
<li>Redraw them at whatever resolution you want</li>
<li>Drop the results into Azahar's <code>load/textures/&lt;TitleID&gt;/</code> directory</li>
</ol>
<p>The extraction is the easy part. The art is yours.</p>
<p>The 3DS library deserves better than being forgotten. A lot of these games have never been experienced on anything larger than a 4-inch screen. Some of them are genuinely beautiful (Bravely Default, Ocarina of Time 3D, Fire Emblem Awakening) and they would look extraordinary at 1080p with hand-crafted textures. That's what this is for.</p>
<hr>
<h2>Bug reports</h2>
<p>Found a bug? <a href="https://github.com/ZoomiesZaggy/3DS-Texture-Forge/issues/new">Open an issue</a> and include your ROM filename, extracted texture count, and a screenshot of what looks wrong.</p>
<hr>
<h2>Download</h2>
<p>Two Windows builds, no installation required:</p>
<ul>
<li><strong><code>3DS Texture Forge.exe</code></strong> (66 MB): GUI, drag-and-drop</li>
<li><strong><code>3ds-tex-extract.exe</code></strong> (28 MB): CLI for batch extractions</li>
</ul>
<p>Executables are attached below this release.</p>
<p>Source code and full supported games list: <a href="https://github.com/ZoomiesZaggy/3DS-Texture-Forge">github.com/ZoomiesZaggy/3DS-Texture-Forge</a></p></body></html><!--EndFragment-->
</body>
