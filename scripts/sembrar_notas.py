"""Carga inicial de notas a partir del historial con ChatGPT (sep. 2026).

Marca como 'escuchado' lo que ya ha pasado por delante —para que no vuelva a
ofrecerse como novedad— y como 'pendiente' lo que quedó apuntado. No inventa
veredictos: si no dijo qué le pareció, no se pone.

Se puede volver a ejecutar sin miedo: no pisa una nota que ya tenga veredicto
propio distinto de 'escuchado'.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import notes  # noqa: E402

ESCUCHADOS = [
    ("Nickelback", "All the Right Reasons"),
    ("Nick Cave & The Bad Seeds", "Let Love In"),
    ("R.E.M.", "Automatic for the People"),
    ("PJ Harvey", "To Bring You My Love"),
    ("Depeche Mode", "Violator"),
    ("The Replacements", "Let It Be"),
    ("Franz Ferdinand", "Franz Ferdinand"),
    ("CAN", "Tago Mago"),
    ("Mort Garson", "Plantasia"),
    ("Ben Folds Five", "Whatever and Ever Amen"),
    ("Mercury Rev", "Yerself Is Steam"),
    ("Lard", "The Power of Lard"),
    ("Mediterráneo", "Tabarca"),
    ("Mediterráneo", "Nº 1 en USA"),
    ("The Stone Roses", "The Stone Roses"),
    ("The Raincoats", "The Raincoats"),
    ("The Stooges", "Raw Power"),
]

# Propuestos y aún sin escuchar
PENDIENTES = [
    ("Man/Woman/Chainsaw", "Cannonball"),
    ("Just Mustard", "WE WERE JUST HERE"),
    ("Adwaith", "Solas"),
    ("The Cramps", "Gravest Gravy"),
    ("The Tubs", "Hard Life"),
    ("Sweeping Promises", "You Say I Romanticize"),
    ("Blind Yeo", "The Lemoine Point"),
    ("Soft Loft", "Throw A Dice"),
]

# Lo que dijo de discos concretos
MATICES = {
    ("CAN", "Tago Mago"): ("no es para mí pero lo entiendo",
                           "Conecta cuando aparece el groove o la estructura; "
                           "se pierde en las zonas abstractas largas. Con este "
                           "disco descubrió su regla sobre lo experimental."),
    ("Mediterráneo", "Tabarca"): ("sin pena ni gloria",
                                  "Le gustó el primer tema y los pasajes "
                                  "instrumentales prog-jazz; los coros y las "
                                  "voces setenteras le parecieron anticuadas."),
}

# Artistas que ya están en su órbita por estas conversaciones
EN_SU_ORBITA = [
    "Joy Division", "Fugazi", "Kate Bush", "Them Crooked Vultures",
    "Fela Kuti", "Yard Act", "Tito Puente", "Machito",
]


def main():
    existentes = notes.cargar()
    ya = existentes["albumes"]
    nuevos = 0

    for artista, album in ESCUCHADOS:
        clave = notes._clave_album(artista, album)
        anterior = ya.get(clave, {}).get("veredicto", "")
        if anterior and anterior != "escuchado":
            continue  # ya opinó algo más preciso: no lo pisamos
        veredicto, nota = MATICES.get((artista, album), ("escuchado", ""))
        notes.anotar("album", artista, veredicto, nota, album)
        nuevos += 1

    for artista, album in PENDIENTES:
        clave = notes._clave_album(artista, album)
        if ya.get(clave, {}).get("veredicto"):
            continue
        notes.anotar("album", artista, "pendiente",
                     "Propuesto en las conversaciones con ChatGPT", album)
        nuevos += 1

    for artista in EN_SU_ORBITA:
        if notes.norm(artista) in existentes["artistas"]:
            continue
        notes.anotar("artista", artista, "escuchado",
                     "Ha aparecido en sus conversaciones de descubrimiento")
        nuevos += 1

    resumen = notes.listar()
    print(f"Añadidas o actualizadas {nuevos} notas.")
    print(f"Total ahora: {resumen['total']} "
          f"({len(resumen['albumes'])} álbumes).")


if __name__ == "__main__":
    main()
