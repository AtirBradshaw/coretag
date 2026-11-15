"""Word lists for Coretag's codes: an adjective + a noun, like `amber-otter`.

Rules for every word (tests/test_codes.py enforces the mechanical ones):
  - short (3-9 letters), common, easy to spell, lowercase a-z only
  - nothing explicit, crude or slang-suggestive, alone or in combination
  - nothing negative or alarming (no fire, storms, death, decay, danger)
  - nothing that reads like a VERDICT on the hardware. A code is printed on a
    report, so something like `rusty-lemon` on a healthy card would undercut it.
    Excluded: temperature (hot, cozy, frost, tundra), speed (fast, swift,
    snail), condition (mint, new, old, worn, shiny, vintage, patchwork),
    trust claims (honest, trusty, certified), rankings (bronze, silver),
    hardware symptoms (humming, whistling = coil whine; skipping = stutter;
    drifting; fiddle = tamper), and buyer slang for a bad item (lemon, brick,
    toast, potato, dud, cactus)
  - nothing that sounds like fraud: no cheetah ("cheater"), no artful
  - no brand or product names (apple, jaguar, falcon, titan, camel, lotus)
  - no common homophones (bear/bare, pear/pair, sail/sale, pier/peer), so a
    code read aloud gets typed correctly
  - no word appears in both lists

Adding words is always safe. Removing a word means codes containing it can
no longer be typed into the lookup box (their links keep working), so only
remove a word if it's genuinely a problem.
"""

ADJECTIVES = (
    # colours
    "amber", "cobalt", "copper", "crimson", "cyan", "emerald", "golden",
    "green", "hazel", "indigo", "ivory", "lavender", "lilac", "magenta",
    "mauve", "navy", "olive", "orange", "peach", "pearl", "pink", "plum",
    "purple", "rosy", "ruby", "russet", "saffron", "sage", "scarlet", "sienna",
    "slate", "tawny", "teal", "topaz", "violet", "yellow", "blue", "coral",
    # nature and places
    "alpine", "autumn", "coastal", "dewy", "leafy", "lunar", "mossy", "misty",
    "northern", "eastern", "southern", "western", "solar", "starry", "sunny",
    "tidal", "woodland", "floral", "sunlit", "inland", "upland", "rural",
    "urban", "royal", "seaside", "orchard", "prairie", "valley", "island",
    "garden",
    # patterns and textures
    "curly", "dotted", "knitted", "quilted", "round", "silken", "striped",
    "wavy", "woolen", "woven", "zigzag", "plaid", "tartan", "velvet",
    "speckled", "spotted", "twisty", "swirly", "bubbly", "frilly", "feathery",
    "paisley", "pleated", "braided", "beaded",
    # friendly character
    "brave", "calm", "cheery", "clever", "curious", "daring", "eager",
    "gentle", "happy", "jolly", "kind", "lively", "lucky", "merry", "mellow",
    "nimble", "noble", "patient", "playful", "plucky", "polite", "proud",
    "witty", "zany", "zesty", "dapper", "chirpy", "bouncy", "breezy", "cosmic",
    "dreamy", "fancy", "gleeful", "humble", "joyful", "keen", "loyal",
    "modest", "peppy", "perky", "regal", "snug", "sporty", "upbeat", "vivid",
    "wise", "friendly", "gallant", "genial", "jaunty", "jovial", "lovely",
    "nifty", "valiant", "bold", "candid", "charming", "comfy", "cuddly",
    "earnest", "festive", "gutsy", "jazzy", "lucid", "mindful", "musical",
    "peaceful", "placid", "poised", "radiant", "savvy", "serene", "snazzy",
    "tranquil", "vibrant", "kindly", "graceful", "tuneful", "wandering",
    "roaming", "dancing", "singing", "smiling", "floating", "gliding",
    "wondering", "dashing",
)

NOUNS = (
    # animals
    "otter", "badger", "bison", "bobcat", "caribou", "cardinal", "chipmunk",
    "condor", "coyote", "crane", "cricket", "dingo", "dolphin", "duck",
    "eagle", "egret", "elk", "emu", "ferret", "finch", "flamingo", "fox",
    "gazelle", "gecko", "gerbil", "gibbon", "giraffe", "goose", "gopher",
    "hamster", "hawk", "hedgehog", "heron", "hippo", "ibex", "ibis", "iguana",
    "jay", "kestrel", "kiwi", "koala", "lark", "lemur", "leopard", "lion",
    "llama", "lobster", "macaw", "magpie", "mallard", "manatee", "marmot",
    "meerkat", "mink", "moose", "narwhal", "newt", "ocelot", "okapi", "orca",
    "oriole", "osprey", "ostrich", "owl", "panda", "panther", "parrot",
    "pelican", "penguin", "pheasant", "pigeon", "plover", "pony", "puffin",
    "quail", "quokka", "rabbit", "raccoon", "raven", "robin", "seal",
    "sparrow", "squid", "starling", "stork", "swan", "tapir", "tiger",
    "toucan", "trout", "walrus", "warbler", "whale", "wombat", "wren", "yak",
    "zebra", "alpaca", "antelope", "armadillo", "bluejay", "butterfly",
    "moth", "lamb", "calf", "foal", "fawn", "cub", "owlet", "octopus",
    "starfish", "seahorse", "squirrel", "cat", "hound", "terrier", "beagle",
    "poodle", "collie", "spaniel", "corgi", "husky", "mole", "vole", "bee",
    "ladybug", "dragonfly", "nuthatch", "nightjar", "chickadee", "bunting",
    "pika", "ermine", "dormouse", "kangaroo", "wallaby", "platypus",
    "sealion", "beluga", "marlin", "perch", "guppy", "goldfish", "seagull",
    "puffer", "oyster", "rooster", "hen", "duckling", "gosling", "piglet",
    "goat", "sheep", "horse", "reindeer", "lioness",
    # plants, trees, flowers, fruit
    "acorn", "aspen", "bamboo", "basil", "birch", "blossom", "cedar",
    "clover", "cypress", "daisy", "fern", "fig", "holly", "iris", "ivy",
    "juniper", "laurel", "lily", "magnolia", "maple", "marigold", "moss",
    "myrtle", "oak", "orchid", "palm", "peony", "pine", "poppy", "sequoia",
    "spruce", "sunflower", "thistle", "tulip", "willow", "yarrow", "zinnia",
    "mango", "papaya", "apricot", "quince", "walnut", "chestnut", "pecan",
    "hazelnut", "cashew", "pistachio", "coconut", "grape", "fennel",
    "parsley", "rosemary", "oregano", "chive", "dill", "sorrel", "heather",
    "bluebell", "buttercup", "daffodil", "dandelion", "foxglove", "gardenia",
    "hibiscus", "hyacinth", "jasmine", "primrose", "petunia", "camellia",
    "dahlia", "aster", "begonia", "cosmos", "freesia", "larkspur",
    "sweetpea", "wisteria", "acacia", "alder", "elm", "hawthorn", "hickory",
    "larch", "linden", "redwood", "rowan", "sycamore", "banyan", "kumquat",
    "guava", "nectarine", "tangerine", "blueberry", "raspberry", "cranberry",
    # landscape and water
    "bay", "beach", "brook", "canyon", "cape", "cliff", "coast", "cove",
    "delta", "dune", "field", "forest", "glade", "glen", "grove", "hill",
    "lagoon", "lake", "marsh", "meadow", "mesa", "oasis", "ocean", "pond",
    "reef", "ridge", "river", "shore", "spring", "summit", "atoll", "savanna",
    "inlet", "estuary", "pebble", "boulder", "wharf", "jetty", "highland",
    "headland", "basin", "bayou", "fountain", "geode", "terrace", "trail",
    "path", "lane", "meander",
    # sky
    "comet", "planet", "star", "moon", "nova", "orbit", "galaxy", "nebula",
    "aurora", "horizon", "rainbow", "sunrise", "cloud", "breeze", "zephyr",
    "dawn", "equinox", "solstice", "quasar", "pulsar", "stardust", "moonbeam",
    "skylark", "sunshine", "daybreak", "sunbeam",
    # music
    "banjo", "cello", "drum", "flute", "guitar", "harp", "oboe", "piano",
    "trumpet", "tuba", "violin", "zither", "harmonica", "mandolin",
    "clarinet", "bugle", "chime", "accordion", "bagpipe", "melody", "chorus",
    "sonata", "ballad", "lullaby", "anthem", "tempo", "encore",
    # everyday objects, places and crafts
    "anchor", "beacon", "button", "candle", "canoe", "compass", "easel",
    "gondola", "kayak", "kite", "lantern", "mitten", "paddle", "pillow",
    "quill", "quilt", "ribbon", "saddle", "sled", "spoon", "teacup",
    "teapot", "trolley", "umbrella", "wagon", "whistle", "kettle", "lamp",
    "ladder", "locket", "mosaic", "origami", "pinwheel", "puzzle", "rocket",
    "scarf", "thimble", "windmill", "banner", "basket", "beret", "bonnet",
    "bobbin", "spindle", "teaspoon", "notebook", "postcard", "parasol",
    "hammock", "lasso", "pendant", "satchel", "rucksack", "tent", "cabin",
    "cottage", "chalet", "castle", "tower", "bridge", "gazebo", "porch",
    "attic", "sundial", "telescope", "globe", "atlas", "map", "voyage",
    "journey", "parade", "picnic", "festival", "carnival", "marble", "yoyo",
    "balloon", "glider", "sailboat", "rowboat", "caravan", "carousel",
    "bicycle", "scooter", "tricycle", "unicycle",
    # food and drink
    "biscuit", "cookie", "cupcake", "dumpling", "noodle", "pancake",
    "popcorn", "pudding", "bagel", "nougat", "toffee", "truffle", "caramel",
    "cocoa", "honey", "mocha", "latte", "sorbet", "gelato", "pretzel",
    "scone", "brioche", "custard", "praline", "marzipan", "strudel", "crepe",
    "granola", "oatmeal", "porridge", "risotto", "ravioli", "lasagna",
    "pesto", "salsa", "chutney", "jelly", "cider", "smoothie", "milkshake",
    "teacake", "shortcake", "flapjack",
    # gems and minerals
    "agate", "beryl", "garnet", "jasper", "onyx", "opal", "quartz",
    "sapphire", "amethyst", "zircon", "obsidian", "crystal", "granite",
    "basalt", "mica", "feldspar",
)
