#include "sqlite3.h"

/* Absent from Turso's reduced header. SQLite's public ABI, used by TrailBase.
 * Link-only: no fabricated implementation and no runtime behavior claim. */
extern int sqlite3_auto_extension(void (*entry_point)(void));
extern void *sqlite3_preupdate_hook(sqlite3 *db,
    void (*callback)(void *, sqlite3 *, int, const char *, const char *, sqlite3_int64, sqlite3_int64),
    void *context);

int main(void) {
    int rc = sqlite3_auto_extension((void (*)(void))0);
    void *previous = sqlite3_preupdate_hook((sqlite3 *)0, 0, 0);
    return rc + (previous != 0);
}
