# openosint.tape — OpenOSINT v2.14.0 cinematic demo
# Run: vhs openosint.tape

Output assets/demo.gif

Set Shell "bash"
Set FontSize 16
Set FontFamily "JetBrains Mono, Courier New"
Set Width 1920
Set Height 1080
Set Theme "Dracula"
Set Padding 24
Set TypingSpeed 55ms
Set PlaybackSpeed 0.85

# Pre-wire the alias so `openosint` launches the demo driver (not recorded).
Hide
Type "alias openosint='python3 openosint_demo.py'"
Enter
Show

# ----------------------------------------------------------------
# Scene 1 — Interactive REPL startup
# ----------------------------------------------------------------

Type "openosint"
Enter
Sleep 1800ms

# ----------------------------------------------------------------
# Scene 2 — Natural language REPL investigation
# ----------------------------------------------------------------

Type "investigate target@example.com"
Enter
Sleep 9000ms

# ----------------------------------------------------------------
# Scene 3 — New tools showcase (ip2location + abuseipdb)
# ----------------------------------------------------------------

Type "check 198.51.100.1 for abuse and location"
Enter
Sleep 5000ms
Sleep 2500ms
