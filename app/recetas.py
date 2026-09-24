"""Recetario: cómo afrontar cada tipo de petición.

Por qué existe: en las primeras pruebas, el modelo del chat improvisaba el
procedimiento cada vez y se saltaba herramientas que le habrían servido (o
usaba las que no tocaban, como la similitud para buscar influencias). Cada
receta fija qué aporta el modelo, qué herramientas usar y en qué orden, el
formato de salida y las trampas ya conocidas. No es una jaula: si una
petición no encaja, se combinan recetas o se improvisa, pero con criterio.
"""

COMUN = [
    "Empieza siempre por curation_guide y my_notes (y taste_profile si la "
    "receta lo pide): su criterio y lo que ya opinó mandan.",
    "Todo candidato pasa por vet_candidates antes de proponerlo.",
    "Antes de crear: resolve (edición original, aviso de >70 min). Tras crear, "
    "los discos quedan como pendientes solos.",
    "Spotify no permite carpetas por la API: si las pide, díselo al principio.",
    "Cuando opine de algo durante la conversación, guárdalo (rate o remember).",
]

RECETAS = {
    # ---------------- DESCUBRIR ----------------
    "menu_cinco": {
        "familia": "descubrir",
        "cuando": "Una lista de 5 discos variada: 'hazme el menú', 'cinco discos que me vayan a flipar'.",
        "modelo": "Elige las cinco piezas y el orden de escucha; escribe una frase por disco.",
        "pasos": [
            "Casillas: afín, histórico, lateral, sorpresa, clásico (ver curation_guide).",
            "La casilla afín o la de novedad sale del radar (encaja_contigo); la sorpresa puede salir de radar.fuera_de_tu_zona si tiene aval.",
            "Histórico y clásico: tu conocimiento + verify si afirmas año o sello.",
            "vet_candidates con los 5 (y 3-4 de reserva) → sustituye lo conocido.",
            "resolve → create_playlist con items en el orden de escucha.",
        ],
        "formato": "Lista numerada en orden de escucha: disco, año, país, casilla y una frase de por qué a él.",
        "trampas": ["Dos discos del mismo género y época: cada casilla debe mover algo distinto.",
                    "Un 'emergente' que es veterano: mira la etapa en vet_candidates."],
    },
    "semana_tematica": {
        "familia": "descubrir",
        "cuando": "Listas de lunes a viernes con un hilo o viaje entre ellas.",
        "modelo": "El hilo narrativo y el título de cada día. Es lo que más valora de estas semanas.",
        "pasos": [
            "taste_profile (fase actual) para anclar el viaje en lo que escucha ahora.",
            "Diseña el arco: qué se desmonta o recorre cada día y cómo converge el viernes.",
            "Cada día con la estructura del menú de cinco; al menos una novedad por día del radar.",
            "vet_candidates con los 25 de golpe (en dos llamadas de 20 si hace falta).",
            "resolve por día → create_playlist por día, con nombre temático.",
        ],
        "formato": "Por día: título, una línea de concepto y los cinco discos con su papel. Cierre: qué se habrá aprendido el viernes.",
        "trampas": ["Repetir artista entre días.", "Días de más de 5 h: vigila minutos en resolve."],
    },
    "novedades_emergentes": {
        "familia": "descubrir",
        "cuando": "'Novedades', 'lo último', 'bandas emergentes', 'carne fresca'.",
        "modelo": "Criterio para elegir entre los candidatos y contar por qué encajan. NO la fuente de nombres.",
        "pasos": [
            "radar (si 'actualizado' tiene más de una semana, radar_update).",
            "Prioriza encaja_contigo triangulados; completa con radio_tastemaker, fresh_releases o music_press.",
            "vet_candidates: etapa 'emergente' o 'consolidado'; fuera veteranos salvo que lo pida.",
            "Si piden castellano, mira candidatos con etiquetas en español o de sellos españoles.",
            "Si un disco aún no ha salido, mete el single con items.",
        ],
        "formato": "Por disco: de dónde ha salido (KEXP, sello, prensa…), por qué a él, y si tiene sesión en directo.",
        "trampas": ["Sacar emergentes de memoria: tu conocimiento tiene fecha de corte.",
                    "Discografías equivocadas cuando el grupo no está en Spotify: artist_releases ya avisa."],
    },
    "como_x_pero_nuevo": {
        "familia": "descubrir",
        "cuando": "'Algo como X que no conozca', 'más cosas en la onda de…'.",
        "modelo": "Qué tiene X que le gusta (voz, garra, bajo, actitud) y buscar ESO, no el género.",
        "pasos": [
            "dossier_artist(X) y my_notes: qué rasgo concreto le engancha de X.",
            "Candidatos: tu criterio + similar_artists (Last.fm + ListenBrainz) + labels_of(X) → label_catalog.",
            "vet_candidates; quita lo conocido.",
        ],
        "formato": "Cada propuesta con el rasgo compartido con X, dicho en una frase.",
        "trampas": ["Similitud = primos obvios del mismo sonido: mezcla con tu criterio y con el sello."],
    },
    "salir_de_la_zona": {
        "familia": "descubrir",
        "cuando": "'Sorpréndeme', 'algo lejano', 'sácame de mi mapa'.",
        "modelo": "Encontrar la puerta de entrada: el anclaje (groove, voz, estructura) desde lo que ya le gusta.",
        "pasos": [
            "curation_guide: regla del anclaje en lo experimental.",
            "radar.fuera_de_tu_zona (lo que tiene aval) + tu conocimiento.",
            "Justifica el puente con algo que ya le gusta ('si te engancha el bajo de X…').",
        ],
        "formato": "Pocas piezas, cada una con su puerta de entrada explícita y qué escuchar primero.",
        "trampas": ["Experimental sin anclaje: le desconecta (Tago Mago)."],
    },
    "iniciacion_genero": {
        "familia": "descubrir",
        "cuando": "'Enséñame el krautrock', 'introdúceme en el slowcore'.",
        "modelo": "El relato: origen, discos clave, ramas, y un orden de escucha que sea un camino.",
        "pasos": [
            "explore_genre (mapa y contexto) y explore_era (lo fechado de verdad).",
            "Enlaza con lo que ya escucha (taste_profile): por dónde le entra.",
            "verify los años que afirmes; vet_candidates.",
        ],
        "formato": "Recorrido de 5-8 paradas en orden, una frase por parada con qué escuchar en ella.",
        "trampas": ["Listas por popularidad de Last.fm tomadas como canon: el canon lo pones tú."],
    },
    "viaje_geografico": {
        "familia": "descubrir",
        "cuando": "'Llévame a Japón', 'la escena de Manchester', 'qué se hace en Argentina'.",
        "modelo": "La historia de la escena y su conexión con lo que él escucha.",
        "pasos": ["explore_scene(lugar, etiqueta)", "radar/radio_tastemaker por si hay algo actual de allí",
                  "vet_candidates y resolve"],
        "formato": "Un recorrido con contexto breve de la escena y una frase por parada.",
        "trampas": ["'Lo más escuchado allí' es gusto mayoritario, no la escena."],
    },

    # ---------------- PROFUNDIZAR ----------------
    "por_donde_empezar": {
        "familia": "profundizar",
        "cuando": "'¿Por dónde empiezo con X?', 'discografía comentada de X'.",
        "modelo": "Qué disco es la mejor puerta PARA ÉL, no el más famoso.",
        "pasos": ["artist_context(X) y verify(X, discography=True)", "my_notes: qué discos de X ya tiene o valoró",
                  "Ordena: puerta de entrada → el imprescindible → el raro que se disfruta después"],
        "formato": "3-4 discos en orden de escucha con el porqué de ese orden.",
        "trampas": ["Años de reedición: usa las fechas de verify."],
    },
    "genealogia": {
        "familia": "profundizar",
        "cuando": "Influencias antes de cada disco o herederos después: 'megalista de influencias de X'.",
        "modelo": "Proponer las influencias concretas de cada disco (entrevistas, reseñas) y el rasgo que pasa de uno a otro.",
        "pasos": ["Usa el prompt 'genealogia'.",
                  "influence_evidence por disco → propón → check_lineage → quita descartados y contemporáneos."],
        "formato": "Bloques por disco, en orden. Cada enlace: rasgo concreto + si está documentado o es tu lectura.",
        "trampas": ["Similitud para influencias: da primos, no abuelos.",
                    "Con discos completos pasa de 10 h: ofrece partirla."],
    },
    "caras_b_rarezas": {
        "familia": "profundizar",
        "cuando": "'Caras B de X', 'lo menos conocido de X', rarezas de un artista que ya le gusta.",
        "modelo": "Saber qué hay fuera de los discos: caras B, EPs, sesiones, versiones.",
        "pasos": ["artist_releases(X) incluye singles y EPs", "my_library: qué tiene ya guardado de X",
                  "resolve con canciones sueltas (items) comprobando que sean las versiones buscadas"],
        "formato": "Lista de canciones con de dónde sale cada una (single, EP, sesión).",
        "trampas": ["Versiones en directo o remasters colados en lugar de la original."],
    },
    "infravalorados": {
        "familia": "profundizar",
        "cuando": "'Discos infravalorados de los 90', 'joyas ocultas de…'.",
        "modelo": "Proponer candidatos con criterio; los datos confirman si son de culto.",
        "pasos": ["Tu lista de sospechosos + explore_era", "find_underrated para separar culto de desconocido",
                  "vet_candidates"],
        "formato": "Cada disco con por qué se le escapó a la gente y por qué a él le puede llegar.",
        "trampas": ["'Infravalorado' con un millón de oyentes: find_underrated lo separa."],
    },
    "segunda_escucha": {
        "familia": "profundizar",
        "cuando": "'Dale otra oportunidad a…', recuperar lo que quedó 'sin pena ni gloria'.",
        "modelo": "Encontrar otra puerta: el tema por el que entrar, el contexto que faltó.",
        "pasos": ["my_notes: veredictos 'sin pena ni gloria' y 'no es para mí pero lo entiendo'",
                  "Para cada uno: una canción puerta y un disco hermano más accesible"],
        "formato": "Por disco: qué pudo fallar, por dónde entrar ahora.",
        "trampas": ["Insistir con lo vetado ('nunca más'): no se toca."],
    },

    # ---------------- MOMENTO ----------------
    "momento_actividad": {
        "familia": "momento",
        "cuando": "Lista para currar, correr, conducir, cenar… (canciones, no discos).",
        "modelo": "Leer el momento (energía, atención) y hacer una curva, no un montón.",
        "pasos": ["my_playlists: si ya tiene una para eso, ampliarla o hacer una hermana",
                  "Mezcla conocido y nuevo (≈70/30 salvo que pida otra cosa)",
                  "resolve con canciones (items) y create_playlist"],
        "formato": "Canciones con arco (arranque, pico, bajada). Duración que pida el momento.",
        "trampas": ["Para concentrarse: nada que exija atención (voces habladas, cambios bruscos)."],
    },
    "seguir_esto": {
        "familia": "momento",
        "cuando": "'Pon algo que siga a esto', 'más como lo que suena'.",
        "modelo": "Continuar la energía y el rasgo de lo que suena.",
        "pasos": ["now_playing", "dossier_artist del que suena", "5-10 canciones que continúen"],
        "formato": "Corta: una tanda para seguir escuchando, sin explicación larga.",
        "trampas": [],
    },
    "preparar_concierto": {
        "familia": "momento",
        "cuando": "'Voy a ver a X', festival, cartel.",
        "modelo": "Qué discos y canciones escuchar antes; en un cartel, qué no perderse.",
        "pasos": ["Concierto: artist_context(X) + disco actual (artist_releases) + canciones clásicas de directo",
                  "Festival: vet_candidates con el cartel → prioriza lo que no conoce y encaja, con aval"],
        "formato": "Concierto: lista para llegar sabiéndose lo nuevo. Festival: a quién ver y por qué.",
        "trampas": ["No inventes setlists: si no los tienes documentados, di que es aproximado."],
    },

    # ---------------- MEMORIA ----------------
    "feedback_semana": {
        "familia": "memoria",
        "cuando": "'Qué tal la semana', te cuenta qué le parecieron los discos.",
        "modelo": "Traducir lo que dice a su escala y detectar patrones.",
        "pasos": ["rate con todas las opiniones de una vez (o que use la página /semana)",
                  "Busca patrones: qué casillas y rasgos funcionaron",
                  "Propón ajustar curation_guide si un patrón se repite (con su visto bueno)"],
        "formato": "Resumen breve: qué funcionó, qué no, qué cambia para la próxima.",
        "trampas": ["Tratar 'no es para mí pero lo entiendo' como fracaso: es un acierto."],
    },
    "resumen_escuchas": {
        "familia": "memoria",
        "cuando": "'Mi mes en música', 'qué he escuchado', 'cómo ha cambiado mi gusto'.",
        "modelo": "Leer tendencias y contarlas con gracia.",
        "pasos": ["taste_profile (fase actual) y listening_history por rangos", "my_notes: descubrimientos del periodo"],
        "formato": "Relato corto con lo que entró, lo que salió y hacia dónde va.",
        "trampas": [],
    },
    "que_opino_de": {
        "familia": "memoria",
        "cuando": "'¿Qué dije de X?', '¿ya escuché Y?'.",
        "modelo": "Responder directo.",
        "pasos": ["check_known o vet_candidates con X", "my_notes"],
        "formato": "Una respuesta corta con su opinión y cuándo la dio.",
        "trampas": [],
    },
}


def indice() -> dict:
    """Todas las recetas por familia, con cuándo usar cada una."""
    familias: dict[str, list] = {}
    for clave, r in RECETAS.items():
        familias.setdefault(r["familia"], []).append({"receta": clave, "cuando": r["cuando"]})
    return {"familias": familias, "comun_a_todas": COMUN,
            "nota": ("Identifica el tipo de petición y pide la receta. Si no encaja "
                     "ninguna, combina las que se parezcan.")}


def receta(clave: str) -> dict:
    r = RECETAS.get(clave)
    if not r:
        return {"error": f"No hay receta '{clave}'", **indice()}
    return {"receta": clave, **r, "comun_a_todas": COMUN}
