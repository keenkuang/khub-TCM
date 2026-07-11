from ...db import Store
def add_animal(store, name, species, breed='', age=0, owner=''):
    store.conn.execute('INSERT INTO vet_patients (name, species, breed, age, owner) VALUES (?,?,?,?,?)', (name, species, breed, age, owner))
    return store.conn.execute('SELECT last_insert_rowid()').fetchone()[0]
def list_animals(store, species=''):
    if species: return store.conn.execute('SELECT * FROM vet_patients WHERE species=? ORDER BY name', (species,)).fetchall()
    return store.conn.execute('SELECT * FROM vet_patients ORDER BY name').fetchall()
