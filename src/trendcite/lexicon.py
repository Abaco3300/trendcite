"""Reference lexicon of common general-English content words.

A word listed here has an everyday meaning outside developer/founder communities
("decision", "human", "apple", "agent", "memory"). Two items sharing only such a word
are frequently about unrelated things, so :mod:`trendcite.cluster` never lets one of
these words link items on its own: a cluster seeded by a common word also needs a
second, specific shared term (see ``cluster.py``).

Words *not* listed here (and not generic or stopwords) are treated as specific
vocabulary: product names, acronyms and technical terms such as "mcp", "kubernetes",
"crdt" or "rust". The list is a hand-curated approximation of the most frequent English
nouns, verbs and adjectives; it is deliberately not tuned to any particular run.
Only singular/base forms are needed: plurals are folded by :func:`text.stem`.
"""

from __future__ import annotations

COMMON_WORDS_TEXT = """
ability able absence absolute academic accept access accident account accurate achieve
acid act action active activity actor actual add addition address admit adult advance
advantage advice affair affect afford afraid age agency agenda agent agree agreement ahead
aid aim air alarm album alive allow alone alternative amazing amount analysis ancient anger
angle angry animal annual answer anxiety apart apparent appeal appear apple application
apply appointment approach appropriate approval approve area argue argument arm army arrange
arrest arrival arrive art artist aspect assessment asset assist assistant associate
association assume attach attack attempt attend attention attitude attract audience author
authority average avoid award aware awareness away awful baby background bad bag balance
ball ban band bank bar base basic basis basket bath battle beach bear beat beautiful beauty
bed beer begin beginning behavior belief believe bell belong benefit bet bid bill bird birth
bit bite bitter black blame blank blind block blood blow blue board boat body bomb bond bone
bonus book boost boot border bore born borrow boss bother bottle bound box boy brain branch
brand brave bread break breakfast breath brick bridge brief bright brilliant bring broad
brother brown brush budget bug burn bus busy button buy buyer cable calm camera camp
campaign cancel cancer candidate cap capable capacity capital captain capture card care
career careful carry cash cast cat catch cause cell center central century certain chain
chair challenge champion chance channel chapter character charge charity chart chat cheap
check cheese chemical chest chicken chief chip choice choose church circle citizen civil
claim class classic classroom clean clear click client climate climb clock closed cloth
clothes cloud club clue coach coast coat coffee cold collapse collect collection college
color column combination combine comfort command comment commercial commission commit
commitment committee common communication comparison compete competition complain complete
complex complicated component concept concern concert conclusion condition conduct
conference confidence confirm conflict confusion connect connection consequence consider
constant construction contact contain content contest context continue contract contrast
contribute control conversation convert cook cookie cool cope copy core corner correct
council count counter couple courage course court cousin cover crash crazy cream create
creative credit crew crime crisis critic criticism cross crowd crucial cry culture cup cure
curious currency current curve custom cut cute cycle damage dance danger dark date daughter
dead deal dear death debate debt decade decide decision deck declare decline deep defeat
defend defense define definition degree delay deliver delivery demand deny depend deposit
depth describe description desert design desire desk destroy detail determine device
diamond die diet difference difficult difficulty digital dinner direct direction director
dirty disaster discount discover discovery discussion disease dish display distance
distinct district divide doctor document dog domain door double doubt draft drag drama draw
drawing dream dress drink drive driver drop drug dry due dust duty eager ear earn earth ease
east eat economic economy edge edition editor education effect effective efficient effort
egg elect election element emergency emotion emotional employ employee employer empty
encourage enemy engine enjoy ensure enter entire entry environment equal equipment error
escape essay essential establish estate estimate evening event evidence evil exact exam
examine example excellent exchange excite excuse executive exercise exist existing exit
expand expect expense experience experiment expert explain explore express expression
extend extent external extra extreme eye face facility factor factory fail failure fair
faith fall false familiar famous fan farm fashion fat father fault favor fear fee feed feel
feeling female fence festival field fight figure fill film final finance financial fine
finger finish fire firm fish fit fix flag flat flight floor flow flower fly focus fold
follow foot force foreign forest forget form formal format fortune forward found foundation
frame freedom fresh fruit fuel fun function fund funny future gain game gap garden gas gate
gather gift girl glass global goal god gold golf grab grade grand grant graph grass green
ground grow growth guard guess guest guy habit hair half hall hand handle hang happen happy
harm hat hate head health healthy hear heart heat heavy height hell hello hero hide highway
hill hire historical history hit hold hole holiday honest honor hope horror horse hospital
host hot hotel house household housing huge hunt hurt ice identify identity ignore ill
illegal image imagine impact implement improve improvement incident include income increase
independent index indicate individual industry influence inform information initial injury
input insight install instance institution instruction insurance intelligence intend
intent interest interesting internal international interview introduce introduction invest
investment invite involve island issue item join joint joke journey judge judgment juice
jump junior jury justice kick kid kill kind king kitchen knee knife knowledge label labor
lack lady lake land landscape lane laptop lawyer lay layer lead leader leadership league
lean learn leave lecture leg legal legend length lesson letter liberal library license lie
lift limit link list listen literature live load loan local location lock logic lonely
loose lose loss loud love lovely loyal luck lunch machine mad magazine magic mail main
maintain major male manage management manager manner map mark marriage master match
material math matter maximum meal mean meaning measure meat media medical medicine medium
meet meeting memory mental mention menu mess message metal method middle might mind mine
minimum minister minor mirror miss mission mistake mix mixture mobile mode modern moment
monitor mood moon moral mother motion motor mountain mouse mouth movement movie muscle
museum music mystery nail name narrow nation national native natural nature neck negative
negotiate neighbor nerve network nice noise normal north nose novel nurse object objective
obvious occasion ocean offer office officer official oil operate operation opinion
opportunity opposite option orange order ordinary organization origin original outcome
output owner package page pain paint pair palace panel panic paper parent park parking
partner party pass passage passenger passion past path patient pattern pause pay payment
peace peak pen penalty pension perfect perform performance period permission permit
personal perspective phase phone photo phrase physical piano pick picture piece pilot pin
pipe pipeline pitch plan plane planet plant plastic plate player pleasure plenty pocket
poem poet police policy political politics pool poor pop popular population port position
positive possession post pot potato potential pound poverty practical practice praise
prayer predict prefer pregnant premium prepare presence present president press pressure
pretend pretty prevent previous pride priest primary prime prince principle print prior
priority prison privacy prize process produce profession professional profile profit
program progress promise promote prompt proof proper property proposal protect protection
proud prove provide province pub pull punch purchase pure purpose push qualify quality
quantity quarter queen quiet quit quote race radio rain raise range rank rate ratio reach
react reaction reader ready reality realize receipt receive recent recipe recognize
recommend record recover red reduce reference reflect reform refuse region regular
relation relationship relative relax release relevant relief religion rely remain remember
remote remove rent repair repeat replace reply represent reputation request require
requirement rescue reserve resident resist resolve resource respect respond response
responsibility rest restaurant restore retain retire return reveal revenue review reward
rice rich ride ring rise risk river road rock role roll roof room root rope rough round
route routine row royal rule rush sad safe safety salary sale salt sample sand save scale
scene schedule scheme school science score scratch screen script sea search season seat
second secret secretary section sector secure security seed seek select selection sell
send senior sense sentence separate sequence series serious serve server session settle
setting shadow shake shame shape share sharp sheet shell shift shine ship shirt shock shoe
shoot shop shot shoulder show shower sick side sign signal significant silence silly
silver similar sing single sister site situation size skill skin sky sleep slice slide
slip smell smile smoke snow social society soft soil soldier solid solution solve song son
sort soul sound soup south space speak special speech speed spell spend spirit split sport
spot spread spring square stable staff stage stake stand standard star state statement
station status stay steal step stick stock stomach stone store storm straight strange
strategy stream street strength stress stretch strike string strong structure struggle
student studio stuff style subject substance succeed success sudden suffer sugar suggest
suit summer sun supply support suppose sure surface surgery surprise survey survive suspect
sweet swim switch symbol table tackle tail talent talk tank tap target task taste tax tea
teach teacher tear technique technology telephone television temperature tend tension term
terrible test text thank theme theory thin threat throat throw ticket tie tight tip tired
title token tone tongue tooth topic total touch tough tour tower town track trade tradition
traffic train training transfer transition transport trap travel treat treatment tree
trend trial trick trip trouble truck true trust truth tune twist type typical ugly unique
unit unity universe university unusual upper upset urban usage usual vacation valuable
value variety vast vehicle venue version victim view village visit visual voice volume
vote wage wait wake walk wall war warm warn warning wash waste watch wave weak wealth weapon
wear weather wedding weekend weight welcome west wet wheel white wide wife wild win wind
window wine wing winner winter wire wise wish witness wonder wood word worker worry worth
wound wrap yard yellow young youth zone
everyone everybody someone somebody something anything nothing everything came became began
bought brought caught chose drew drove fell felt fought found gave grew held kept knew led
left lost meant met paid ran sat saw sent shot sold spent spoke stood taught told thought
threw took understood won wore wrote tech
"""

COMMON_WORDS = frozenset(COMMON_WORDS_TEXT.split())
