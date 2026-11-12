"""Word lists for the deterministic safety layer.

Short on purpose. These lists catch the obvious cases cheaply and predictably. The model judge
covers what a list cannot: meaning, tone, context and other languages. English only.

Words are matched whole, with common endings added (hit, hits, hitting), so "hat" never trips
"hate" and "class" never trips a curse. Words whose meaning depends on context (kick, oven,
weed) are left to the judge so that ordinary routines are not refused.

Changing this file changes what a child can hear. It needs a human code owner's review.
"""

# Never right in a song for a three to six year old.
UNSAFE = (
    # violence and weapons
    "kill", "murder", "stab", "shoot", "punch", "hit", "slap", "smack", "spank",
    "fight", "fought", "hurt", "blood", "bleed", "die", "dying", "dead", "death",
    "gun", "knife", "knives", "bomb", "weapon", "war", "suicide",
    # scaring a child into doing something
    "monster", "ghost", "scary", "nightmare", "bogeyman", "boogeyman", "devil", "demon",
    "or else",
    # shaming
    "stupid", "dumb", "idiot", "ugly", "fat", "naughty", "hate", "crybaby", "cry baby",
    "loser", "lazy", "brat", "bad boy", "bad girl", "shut up",
    # alcohol, smoking, drugs
    "beer", "wine", "vodka", "whiskey", "drunk", "alcohol", "cigarette", "smoke", "vape", "drug",
    # adult content and swearing
    "sex", "sexy", "porn", "nude", "damn", "hell", "crap", "shit", "fuck", "bitch", "ass",
    "asshole", "piss", "bastard",
    # secrets and strangers
    "secret", "stranger", "don't tell", "dont tell", "do not tell",
)  # fmt: skip

# A song that makes taking medicine fun is a poisoning risk. Out of scope for the prototype.
MEDICINE = ("medicine", "medication", "pill", "vitamin", "dose")

# Music artists and screen characters. The music provider's terms forbid artist names and song
# titles in what we send it, and a character's name is someone else's property. Plain toy words
# (blocks, dolls, legos) are fine.
BRANDS = (
    "disney", "pixar", "elsa", "olaf", "moana", "encanto", "mickey", "minnie", "paw patrol",
    "peppa", "bluey", "cocomelon", "baby shark", "pinkfong", "blippi", "ms rachel",
    "miss rachel", "sesame street", "elmo", "daniel tiger", "wiggles", "raffi", "barney",
    "pokemon", "pikachu", "mario", "minecraft", "roblox", "fortnite", "spiderman",
    "spider man", "batman", "superman", "super man", "barbie", "hello kitty", "marvel",
    "star wars", "harry potter", "nintendo", "youtube", "tiktok", "netflix", "spotify",
    "taylor swift", "beyonce", "drake", "kanye", "eminem", "ed sheeran", "billie eilish",
    "bts", "beatles", "michael jackson", "justin bieber", "ariana grande", "lady gaga",
    "rihanna", "adele", "bruno mars", "harry styles", "olivia rodrigo",
)  # fmt: skip

# Asking for a copy of existing music. Checked on what a parent types, not on finished lyrics,
# where "that sounds like fun" is an ordinary line.
IMITATION = (
    "in the style of", "style of", "sounds like", "sound like", "like the song", "tune of",
    "cover of", "remix", "parody", "sung by", "voice of", "theme song", "soundtrack",
    "karaoke", "lyrics of", "lyrics to", "version of",
)  # fmt: skip

# Text aimed at the model rather than at the song. Checked on what a parent types.
INJECTION = (
    "ignore", "disregard", "override", "jailbreak", "prompt", "instruction", "assistant",
    "output", "system prompt", "you are now", "act as", "from now on", "developer mode",
    "language model", "ai model", "forget everything", "forget the rules", "new rules",
    "instead write", "respond with", "reply with", "write a rap",
)  # fmt: skip

# Hints that someone is about to give personal details. Digits and symbols are already refused
# when the brief is read, so phone numbers, emails and links cannot be typed at all.
CONTACT = (
    "address", "phone number", "last name", "surname", "password", "email", "zip code",
    "date of birth", "social security",
)  # fmt: skip
