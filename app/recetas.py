"""Recetario: cómo afrontar cada tipo de petición.

Cuidado con lo que esto puede provocar: una receta demasiado detallada
convierte al modelo en alguien que rellena un formulario, y una lista de
herramientas en orden hace que todas las listas salgan de las mismas
fuentes. Por eso cada receta dice sobre todo QUÉ tiene que pensar el
modelo, y solo nombra una herramienta cuando es la única forma de saber
algo (lo nuevo, lo que ya conoce, las fechas). Las recetas son un suelo,
no un techo.
"""

PRINCIPIOS = [
    "Las recetas son un suelo, no un techo. Si ves algo mejor, sal de ellas.",
    "Piensa antes de buscar: haz tu lista desde tu conocimiento y tu criterio, y "
    "usa las herramientas para comprobar, no para inspirarte. Excepción: lo "
    "nuevo y lo emergente, donde tu memoria tiene fecha de corte y el radar manda.",
    "Lo obvio no es malo; lo malo es lo obvio por inercia. Tu tendencia es ir a "
    "lo más citado de cada escena, así que piensa más candidatos de los que "
    "necesitas y quédate con los que MEJOR sirven a la idea. Un clásico que él "
    "no ha escuchado y le abre el gusto es un acierto. Pregúntate por cada "
    "pieza: ¿está porque es la mejor para esto o porque es la primera que me salió?",
    "Si la petición NO es de descubrir (un momento, una sensación, un viaje), "
    "puede entrar algo que ya conoce si encaja de diez: hace de ancla. Pocas "
    "piezas y dilo ('esta ya la conoces, pero es la que mejor cuenta esto'). "
    "Si pide descubrir, lo conocido fuera; lo rozado sí vale.",
    "vet_candidates siempre: 'ya_propuestos_antes' y 'diversidad' son una "
    "alarma, no una prohibición. Si la concentración es la idea (una escena, "
    "una década), está bien; si no la buscabas, revisa.",
    "Di de dónde sale cada propuesta (tu criterio, el radar, la prensa…) y "
    "separa lo documentado de tu lectura.",
    "Antes de crear, resolve. Spotify no permite carpetas por la API.",
    "Si opina durante la conversación, guárdalo con rate o remember.",
]

RECETAS = {
    # ---------------- PETICIÓN ABIERTA ----------------
    "peticion_libre": {
        "familia": "abierta",
        "cuando": "Cualquier cosa que no sea un género: una sensación, una imagen, "
                  "una ciudad, una película, 'algo que suene a…'. En la duda, esta.",
        "piensa": "Traduce la petición a rasgos escuchables: tempo, textura, voz, "
                  "producción, instrumentos, época, idioma. NO existe dato de energía "
                  "o tempo en las herramientas: es tu oído, dilo así.",
        "hazlo": ["Escríbele primero 'Lo he entendido como: …' en una o dos líneas y "
                  "deja que lo corrija si la petición es ambigua.",
                  "Busca por rasgo, no por género: el rasgo cruza géneros y países.",
                  "Las etiquetas de ánimo de Last.fm (explore_genre) sirven de "
                  "comprobación, no de fuente."],
        "cuidado": ["Irte al género que suele asociarse a la palabra ('triste' → "
                    "slowcore siempre). Una sensación tiene muchas músicas."],
    },
    "hilo_no_genero": {
        "familia": "abierta",
        "cuando": "Un hilo transversal: un productor, un estudio, un instrumento, "
                  "una técnica vocal, un año, una portada, un sello.",
        "piensa": "Qué huella deja ese hilo en el sonido y cómo se reconoce de un "
                  "disco a otro. El hilo tiene que oírse, no solo figurar en los créditos.",
        "hazlo": ["Sello: labels_of y label_catalog. Año: explore_era. Productor o "
                  "estudio: tu conocimiento, comprobando años con verify.",
                  "Mezcla épocas y países que compartan el hilo."],
        "cuidado": ["Quedarte con los tres discos famosos del productor."],
    },

    # ---------------- DESCUBRIR ----------------
    "menu_cinco": {
        "familia": "descubrir",
        "cuando": "Una tanda de 5 discos variada.",
        "piensa": "Cinco piezas que se muevan en ejes distintos (afín, histórico, "
                  "lateral, sorpresa, clásico: ver curation_guide) y un orden de escucha.",
        "hazlo": ["Al menos la novedad sale del radar.", "Una frase por disco: por qué a él."],
        "cuidado": ["Dos discos que mueven el mismo eje."],
    },
    "semana_tematica": {
        "familia": "descubrir",
        "cuando": "Listas de lunes a viernes con un hilo entre ellas.",
        "piensa": "El arco de la semana: qué se recorre cada día y cómo converge. "
                  "Es lo que más valora de estas semanas.",
        "hazlo": ["Ancla el viaje en su fase actual (taste_profile).",
                  "Cada día como un menú de cinco; una novedad del radar por día.",
                  "Los 25 por vet_candidates y mira 'diversidad' del conjunto."],
        "cuidado": ["Repetir artista entre días.", "Que los cinco días sean el mismo país y década."],
    },
    "novedades_emergentes": {
        "familia": "descubrir",
        "cuando": "Novedades, lo último, emergentes, carne fresca.",
        "piensa": "Criterio para elegir y contar por qué encajan. Aquí NO eres la "
                  "fuente de nombres: tu memoria no sabe qué ha salido.",
        "hazlo": ["radar (radar_update si tiene más de una semana); completa con "
                  "radio_tastemaker, fresh_releases o music_press.",
                  "Etapa emergente o consolidado; veteranos solo si los pide."],
        "cuidado": ["Sacar emergentes de memoria.", "Tomar el radar entero sin criterio: "
                    "que mande el gusto, no la puntuación."],
    },
    "como_x_pero_nuevo": {
        "familia": "descubrir",
        "cuando": "'Algo como X que no conozca'.",
        "piensa": "Qué rasgo concreto de X le engancha (my_notes y lo que diga) y "
                  "busca ESE rasgo, aunque esté en otro género.",
        "hazlo": ["similar_artists solo como contraste: da primos obvios del mismo sonido."],
        "cuidado": ["Devolver la lista de 'similares' de Last.fm con otras palabras."],
    },
    "salir_de_la_zona": {
        "familia": "descubrir",
        "cuando": "Sorpréndeme, algo lejano, antídoto a lo que llevo escuchando.",
        "piensa": "Mira su fase actual (taste_profile) y ve a otro sitio a propósito, "
                  "pero con una puerta de entrada desde algo que ya le gusta.",
        "hazlo": ["radar.fuera_de_tu_zona para lo actual con aval.",
                  "Cada pieza con su puente explícito."],
        "cuidado": ["Experimental sin anclaje: le desconecta."],
    },
    "escena_o_genero": {
        "familia": "descubrir",
        "cuando": "Enséñame un género, una escena, un país o una ciudad.",
        "piensa": "El relato (origen, ramas, conexiones) y un camino de escucha, no "
                  "un canon de los más famosos. Incluye la rama menos contada.",
        "hazlo": ["explore_genre / explore_era / explore_scene para fechas y "
                  "contraste; artist_context (formacion_y_parentesco) para ver quién tocaba con quién."],
        "cuidado": ["'Lo más escuchado' de un sitio es gusto mayoritario, no la escena."],
    },
    "escucha_a_ciegas": {
        "familia": "descubrir",
        "cuando": "Quiere escuchar sin prejuicios.",
        "piensa": "Una lista que funcione sin saber de quién es cada cosa.",
        "hazlo": ["Crea la playlist con nombre neutro y NO le digas los discos en el chat.",
                  "Guarda la clave con remember (nota general) para revelarla luego.",
                  "Al revelar, recoge su veredicto con rate."],
        "cuidado": ["Spotify enseña el artista: funciona si él no mira la pantalla."],
    },

    # ---------------- PROFUNDIZAR ----------------
    "por_donde_empezar": {
        "familia": "profundizar",
        "cuando": "Por dónde empiezo con X; discografía comentada.",
        "piensa": "Qué disco es la mejor puerta PARA ÉL, no el más famoso, y el orden después.",
        "hazlo": ["verify(X, discography=True) para las fechas; my_notes por lo que ya valoró."],
        "cuidado": ["Años de reedición."],
    },
    "genealogia": {
        "familia": "profundizar",
        "cuando": "Influencias antes de cada disco o herederos después.",
        "piensa": "Influencias concretas de cada disco (entrevistas, reseñas) y el rasgo que pasa.",
        "hazlo": ["Prompt 'genealogia': influence_evidence → propón → check_lineage."],
        "cuidado": ["Similitud no es influencia.", "Las influencias 'de manual' "
                    "(Velvet, Stooges…) valen si son de verdad; busca también las menos citadas."],
    },
    "arbol_de_musicos": {
        "familia": "profundizar",
        "cuando": "Miembros, proyectos paralelos, de dónde salió un grupo.",
        "piensa": "Qué aporta cada miembro y qué proyectos suenan distinto al principal.",
        "hazlo": ["artist_context: formacion_y_parentesco (MusicBrainz) da la formación y los otros grupos de cada miembro."],
        "cuidado": ["Proyectos homónimos: comprueba con vet_candidates."],
    },
    "versiones": {
        "familia": "profundizar",
        "cuando": "Versiones, originales, cadenas de covers.",
        "piensa": "Qué cambia cada versión. Solo las que conozcas con seguridad.",
        "hazlo": ["resolve con canciones sueltas; si no aparece, dilo."],
        "cuidado": ["Inventar versiones que no existen."],
    },
    "rarezas_e_infravalorados": {
        "familia": "profundizar",
        "cuando": "Caras B, rarezas, joyas ocultas, infravalorados.",
        "piensa": "Por qué se le escapó a la gente y por qué a él le puede llegar.",
        "hazlo": ["find_underrated separa culto de desconocido; artist_releases para singles y EPs."],
        "cuidado": ["'Infravalorado' con un millón de oyentes."],
    },
    "segunda_escucha": {
        "familia": "profundizar",
        "cuando": "Recuperar lo que quedó 'sin pena ni gloria'.",
        "piensa": "Otra puerta: la canción por la que entrar, el contexto que faltó.",
        "hazlo": ["my_notes: veredictos tibios."],
        "cuidado": ["Lo marcado 'nunca más' no se toca."],
    },

    # ---------------- MOMENTO ----------------
    "momento": {
        "familia": "momento",
        "cuando": "Para currar, correr, conducir, una cena, un viaje, 'algo que siga a esto'.",
        "piensa": "La curva del momento (arranque, pico, bajada) y cuánta atención pide. "
                  "Canciones, no discos, salvo que diga lo contrario.",
        "hazlo": ["now_playing si es 'algo que siga'.", "Viaje a un sitio: su escena "
                  "(explore_scene) mezclada con música para el trayecto.",
                  "Con gente que no comparte su gusto: puntos de encuentro sin traicionarle."],
        "cuidado": ["Para concentrarse, nada que exija atención."],
    },
    "concierto": {
        "familia": "momento",
        "cuando": "Voy a ver a X; un festival.",
        "piensa": "Qué llevarse aprendido; en un cartel, a quién no perderse.",
        "hazlo": ["Cartel entero por vet_candidates: prioriza lo que no conoce y encaja."],
        "cuidado": ["No inventes setlists."],
    },

    # ---------------- MEMORIA ----------------
    "repaso": {
        "familia": "memoria",
        "cuando": "Qué tal la semana, qué he escuchado, qué dije de X.",
        "piensa": "Traducir lo que dice a su escala y ver patrones.",
        "hazlo": ["rate en una llamada; taste_profile y listening_history para tendencias; my_notes."],
        "cuidado": ["'No es para mí pero lo entiendo' es un acierto, no un fallo."],
    },
}


def indice() -> dict:
    familias: dict[str, list] = {}
    for clave, r in RECETAS.items():
        familias.setdefault(r["familia"], []).append({"receta": clave, "cuando": r["cuando"]})
    return {"familias": familias, "principios": PRINCIPIOS}


def receta(clave: str) -> dict:
    r = RECETAS.get(clave)
    if not r:
        return {"error": f"No hay receta '{clave}'", **indice()}
    return {"receta": clave, **r, "principios": PRINCIPIOS}
