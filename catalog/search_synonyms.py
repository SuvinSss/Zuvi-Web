"""English / Manglish / Malayalam grocery synonyms for public search.

Each group lists names a shopper may type for the same item. A search for any
term in a group also matches products named (or keyworded) with the others.
Add new groups or spellings here; keep terms lowercase.
"""

import re

SYNONYM_GROUPS = (
    # Rice and grains
    ("rice", "ari", "അരി"),
    ("matta rice", "kuthari", "kuthari ari", "red rice", "rose matta", "കുത്തരി"),
    ("raw rice", "pachari", "pacha ari", "പച്ചരി"),
    ("boiled rice", "puzhukkalari", "puzhungal ari", "പുഴുക്കലരി"),
    ("basmati rice", "biriyani ari", "biryani rice", "biriyani rice"),
    ("wheat", "gothambu", "gotham", "ഗോതമ്പ്"),
    ("broken wheat", "nurukku gothambu", "dalia"),
    ("rice flakes", "aval", "avil", "poha", "അവൽ"),
    ("semolina", "rava", "ravva", "sooji", "suji", "റവ"),
    ("vermicelli", "semiya", "semiya payasam", "സേമിയ"),
    ("ragi", "finger millet", "panjapullu", "muthari", "റാഗി"),
    # Flours
    ("wheat flour", "atta", "gothambu podi", "ഗോതമ്പ് പൊടി"),
    ("rice flour", "ari podi", "aripodi", "അരിപ്പൊടി"),
    ("puttu flour", "puttu podi", "puttupodi", "പുട്ടുപൊടി"),
    ("appam flour", "appam podi", "palappam podi", "അപ്പം പൊടി"),
    ("idiyappam flour", "idiyappam podi", "pathiri podi", "pathiripodi"),
    ("all purpose flour", "maida", "മൈദ"),
    ("gram flour", "besan", "kadala podi", "kadalamavu", "കടലമാവ്"),
    ("corn flour", "cornflour", "corn starch"),
    # Pulses and lentils
    ("dal", "dhal", "parippu", "paruppu", "പരിപ്പ്"),
    ("toor dal", "tur dal", "thuvara parippu", "thuvaraparippu", "തുവരപ്പരിപ്പ്"),
    ("moong dal", "cherupayar parippu", "split green gram"),
    ("green gram", "cherupayar", "cherupayaru", "moong", "ചെറുപയർ"),
    ("black gram", "urad dal", "urad", "uzhunnu", "uzhunn", "ഉഴുന്ന്"),
    ("bengal gram", "chana", "kadala", "black chana", "കടല"),
    ("chana dal", "kadala parippu", "kadalaparippu", "കടലപ്പരിപ്പ്"),
    ("chickpeas", "kabuli chana", "vella kadala", "vellakadala", "വെള്ളക്കടല"),
    ("red lentil", "masoor dal", "masoor", "chuvanna parippu"),
    ("horse gram", "muthira", "മുതിര"),
    ("cowpea", "vanpayar", "van payar", "lobia", "വൻപയർ"),
    ("green peas", "pattani", "pachapattani", "matar", "പട്ടാണി"),
    ("rajma", "kidney beans", "rajmah"),
    # Oils and ghee
    ("coconut oil", "velichenna", "velichenn", "velichena", "വെളിച്ചെണ്ണ"),
    ("oil", "enna", "എണ്ണ"),
    ("sunflower oil", "sunflower enna", "sooryakanthi enna"),
    ("gingelly oil", "sesame oil", "nallenna", "nalla enna", "til oil", "നല്ലെണ്ണ"),
    ("palm oil", "palmolein", "pamoil", "pamolin"),
    ("groundnut oil", "kadala enna", "peanut oil"),
    ("mustard oil", "kaduku enna"),
    ("ghee", "neyyu", "ney", "neyy", "നെയ്യ്"),
    # Spices and masala
    ("salt", "uppu", "ഉപ്പ്"),
    ("chilli", "chili", "mulaku", "mulak", "മുളക്"),
    ("red chilli", "kashmiri chilli", "unakka mulaku", "vattal mulaku", "ഉണക്കമുളക്"),
    ("green chilli", "pacha mulaku", "pachamulaku", "പച്ചമുളക്"),
    ("chilli powder", "mulaku podi", "mulakupodi", "മുളകുപൊടി"),
    ("kashmiri chilli powder", "kashmiri mulaku podi"),
    ("pepper", "black pepper", "kurumulaku", "kurumulak", "കുരുമുളക്"),
    ("pepper powder", "kurumulaku podi"),
    ("turmeric", "manjal", "മഞ്ഞൾ"),
    ("turmeric powder", "manjal podi", "manjalpodi", "മഞ്ഞൾപ്പൊടി"),
    ("coriander", "malli", "dhania", "മല്ലി"),
    ("coriander powder", "malli podi", "mallipodi", "മല്ലിപ്പൊടി"),
    ("coriander leaves", "malli ila", "malliyila", "cilantro"),
    ("mustard", "mustard seeds", "kaduku", "kadugu", "കടുക്"),
    ("cumin", "jeera", "jeerakam", "jeerakom", "ജീരകം"),
    ("fennel", "perinjeerakam", "perum jeerakam", "saunf", "പെരുംജീരകം"),
    ("fenugreek", "uluva", "methi", "ഉലുവ"),
    ("cardamom", "elakkaya", "elaykka", "elakka", "ഏലക്ക"),
    ("cloves", "grambu", "karayampoo", "ഗ്രാമ്പൂ"),
    ("cinnamon", "karuvapatta", "karuvappatta", "patta", "കറുവപ്പട്ട"),
    ("bay leaf", "vayana ila", "tej patta"),
    ("asafoetida", "kayam", "hing", "കായം"),
    ("garam masala", "garam masala podi"),
    ("meat masala", "irachi masala", "erachi masala"),
    ("chicken masala", "kozhi masala"),
    ("fish masala", "meen masala", "meen curry masala"),
    ("sambar powder", "sambar podi", "sambar masala"),
    ("rasam powder", "rasam podi"),
    ("curry leaves", "kariveppila", "kariveppila", "karivepila", "കറിവേപ്പില"),
    ("tamarind", "puli", "വാളൻപുളി"),
    ("kudampuli", "kodampuli", "gamboge", "malabar tamarind", "കുടംപുളി"),
    ("garlic", "veluthulli", "veluthully", "വെളുത്തുള്ളി"),
    ("ginger", "inji", "ഇഞ്ചി"),
    ("dry ginger", "chukku", "ചുക്ക്"),
    # Sugar and sweeteners
    ("sugar", "panchasara", "pancharra", "പഞ്ചസാര"),
    ("jaggery", "sharkara", "sarkara", "chakkara", "ശർക്കര"),
    ("palm jaggery", "karupetti", "panam sharkara"),
    ("honey", "then", "theen", "തേൻ"),
    ("sugar candy", "kalkandam", "kalkandu", "കൽക്കണ്ടം"),
    # Vegetables
    ("onion", "big onion", "savala", "savola", "സവാള"),
    ("small onion", "shallots", "shallot", "cheriya ulli", "chuvannulli", "ചുവന്നുള്ളി"),
    ("tomato", "thakkali", "തക്കാളി"),
    ("potato", "urulakizhangu", "urulakkizhangu", "aloo", "ഉരുളക്കിഴങ്ങ്"),
    ("tapioca", "kappa", "cassava", "kolli", "കപ്പ"),
    ("drumstick", "muringakka", "muringakaya", "മുരിങ്ങക്ക"),
    ("raw banana", "kaya", "pacha kaya", "plantain", "nendrakkaya", "കായ"),
    ("bitter gourd", "pavakka", "pavaykka", "പാവയ്ക്ക"),
    ("snake gourd", "padavalanga", "പടവലങ്ങ"),
    ("ash gourd", "kumbalanga", "കുമ്പളങ്ങ"),
    ("pumpkin", "mathanga", "മത്തങ്ങ"),
    ("cucumber", "vellarikka", "kakkiri", "വെള്ളരിക്ക"),
    ("ladies finger", "okra", "bhindi", "vendakka", "വെണ്ടയ്ക്ക"),
    ("brinjal", "eggplant", "vazhuthananga", "vazhuthanga", "വഴുതനങ്ങ"),
    ("beans", "green beans", "payar", "പയർ"),
    ("long beans", "achinga", "achinga payar", "അച്ചിങ്ങ"),
    ("cabbage", "muttakose", "muttakoos", "കാബേജ്"),
    ("carrot", "carrat", "കാരറ്റ്"),
    ("beetroot", "beet", "ബീറ്റ്റൂട്ട്"),
    ("yam", "chena", "elephant foot yam", "ചേന"),
    ("colocasia", "chembu", "taro", "ചേമ്പ്"),
    ("sweet potato", "madhurakizhangu", "chakkarakizhangu"),
    ("spinach", "cheera", "amaranth", "ചീര"),
    ("mint", "pudina", "puthina", "പുതിന"),
    ("lemon", "naranga", "cherunaranga", "lime", "നാരങ്ങ"),
    ("raw mango", "pacha manga", "manga", "മാങ്ങ"),
    ("coconut", "thenga", "thenga", "നാളികേരം", "തേങ്ങ"),
    ("grated coconut", "chirakiya thenga", "thenga chirakiyathu"),
    ("coconut milk", "thenga paal", "thengapal", "thenga pal"),
    # Fruits
    ("banana", "pazham", "pazhum", "പഴം"),
    ("nendran banana", "nenthrapazham", "nendrapazham", "ethapazham", "ഏത്തപ്പഴം"),
    ("mango", "manga", "mambazham", "മാമ്പഴം"),
    ("jackfruit", "chakka", "ചക്ക"),
    ("pineapple", "kaithachakka", "kaitha chakka", "പൈനാപ്പിൾ"),
    ("papaya", "kappalanga", "omakka", "papaya kaya", "പപ്പായ"),
    ("guava", "pera", "perakka", "പേരയ്ക്ക"),
    ("orange", "orange naranga", "madhura naranga"),
    ("grapes", "munthiri", "munthiringa", "മുന്തിരി"),
    ("pomegranate", "mathalam", "mathalanaranga", "മാതളം"),
    ("watermelon", "thannimathan", "thannimathan", "തണ്ണിമത്തൻ"),
    ("dates", "eenthapazham", "eethapazham", "ഈന്തപ്പഴം"),
    # Dry fruits and nuts
    ("cashew", "cashew nut", "kashuvandi", "andiparippu", "kasuvandi", "അണ്ടിപ്പരിപ്പ്"),
    ("raisins", "unakka munthiri", "kismis", "kishmish", "ഉണക്കമുന്തിരി"),
    ("groundnut", "peanut", "kappalandi", "nilakkadala", "കപ്പലണ്ടി"),
    ("almond", "badam", "ബദാം"),
    # Dairy, eggs, meat, fish
    ("milk", "paal", "pal", "പാൽ"),
    ("curd", "yogurt", "thairu", "thayir", "തൈര്"),
    ("buttermilk", "moru", "sambaram", "മോര്"),
    ("butter", "venna", "വെണ്ണ"),
    ("paneer", "cottage cheese"),
    ("egg", "eggs", "mutta", "മുട്ട"),
    ("chicken", "kozhi", "kozhiyirachi", "കോഴി"),
    ("beef", "beef irachi", "pothirachi", "pothu irachi", "ബീഫ്"),
    ("mutton", "goat meat", "aattirachi", "aadu irachi"),
    ("meat", "irachi", "erachi", "ഇറച്ചി"),
    ("fish", "meen", "മീൻ"),
    ("dried fish", "unakka meen", "unakkameen", "ഉണക്കമീൻ"),
    ("sardine", "mathi", "chaala", "chala", "മത്തി"),
    ("mackerel", "ayala", "അയല"),
    ("prawns", "shrimp", "chemmeen", "konju", "ചെമ്മീൻ"),
    # Beverages and snacks
    ("tea", "chaya", "chai", "tea powder", "chaya podi", "ചായ"),
    ("coffee", "kappi", "coffee powder", "kaapi podi", "കാപ്പി"),
    ("biscuit", "biscuits", "biskut", "ബിസ്കറ്റ്"),
    ("banana chips", "kaya varuthathu", "kaya chips", "upperi", "ഉപ്പേരി"),
    ("jaggery banana chips", "sharkara upperi", "sharkara varatti"),
    ("tapioca chips", "kappa chips", "kappa varuthathu"),
    ("mixture", "mixture namkeen"),
    ("murukku", "muruku", "chakli", "മുറുക്ക്"),
    ("pappad", "papad", "pappadam", "papadam", "പപ്പടം"),
    ("pickle", "achar", "achaar", "uppilittathu", "അച്ചാർ"),
    ("mango pickle", "manga achar", "kadumanga"),
    ("lemon pickle", "naranga achar", "naranga achar"),
    ("bread", "rotti", "റൊട്ടി"),
    ("payasam mix", "payasam", "പായസം"),
    # Household
    ("soap", "sopp", "soppu", "സോപ്പ്"),
    ("detergent", "washing powder", "alakku podi", "soap podi"),
    ("matchbox", "theepetti", "theeppetti", "തീപ്പെട്ടി"),
    ("camphor", "karpooram", "കർപ്പൂരം"),
    ("incense sticks", "agarbathi", "chandanathiri", "ചന്ദനത്തിരി"),
    ("broom", "choolu", "chool", "ചൂല്"),
    ("water", "vellam", "വെള്ളം"),
)

_WORD = r"[^\W_]"


def _normalize(text):
    return " ".join((text or "").casefold().split())


def _phrase_pattern(term):
    # Whole-word/phrase match so "ari" does not match inside "marie".
    return re.compile(rf"(?<!{_WORD}){re.escape(term)}(?!{_WORD})")


_TERM_GROUPS = {}
for _group in SYNONYM_GROUPS:
    _terms = tuple(dict.fromkeys(_normalize(t) for t in _group))
    for _term in _terms:
        _TERM_GROUPS.setdefault(_term, []).append(_terms)
# Longest first so "coconut oil" wins over "oil" and "rice flour" over "rice".
_TERMS_BY_LENGTH = sorted(_TERM_GROUPS, key=len, reverse=True)
_PATTERNS = {term: _phrase_pattern(term) for term in _TERMS_BY_LENGTH}


def _matched_terms(text):
    text = _normalize(text)
    found = []
    for term in _TERMS_BY_LENGTH:
        pattern = _PATTERNS[term]
        if pattern.search(text):
            found.append(term)
            # Consume the match so shorter terms inside it don't also expand.
            text = pattern.sub(" | ", text)
    return found


def _synonyms_of(terms):
    synonyms = []
    for term in terms:
        for group in _TERM_GROUPS[term]:
            synonyms.extend(group)
    return list(dict.fromkeys(synonyms))


def expand_terms(query):
    """Return the query plus every synonym of a dictionary term found in it."""
    query = _normalize(query)
    if not query:
        return []
    return list(dict.fromkeys([query, *_synonyms_of(_matched_terms(query))]))


def keywords_for_name(name, existing=""):
    """Comma-separated synonyms implied by name that aren't in name/existing yet."""
    present = _normalize(f"{name} {existing}")
    missing = [
        term for term in _synonyms_of(_matched_terms(name))
        if not _phrase_pattern(term).search(present)
    ]
    return ", ".join(missing)


def is_short_ascii(term):
    """Short Latin synonyms need word boundaries in SQL to avoid noisy matches."""
    return term.isascii() and len(term) <= 4
