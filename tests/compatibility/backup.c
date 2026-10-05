#include "fixture.h"

int main(int argc, char **argv) {
    int rc = engine_check();
    if (rc) return rc;
    require(argc == 3, "source and destination path arguments");
    sqlite3 *source = NULL, *dest = NULL;
    require(sqlite3_open(argv[1], &source) == SQLITE_OK, "source open");
    require(sqlite3_open(argv[2], &dest) == SQLITE_OK, "destination open");
    execute(source, "CREATE TABLE backup_control (value INTEGER)");
    execute(source, "INSERT INTO backup_control VALUES (42)");
    puts("CALL sqlite3_backup_init");
    fflush(stdout);
    void *backup = sqlite3_backup_init(dest, "main", source, "main");
    require(backup != NULL, "backup init");
    require(sqlite3_backup_step(backup, -1) == SQLITE_DONE, "backup step");
    require(sqlite3_backup_finish(backup) == SQLITE_OK, "backup finish");
    sqlite3_stmt *stmt = prepare(dest, "SELECT value FROM backup_control");
    require(sqlite3_step(stmt) == SQLITE_ROW && sqlite3_column_int64(stmt, 0) == 42, "backup value");
    require(sqlite3_step(stmt) == SQLITE_DONE, "one backup row");
    require(sqlite3_finalize(stmt) == SQLITE_OK, "backup read finalize");
    require(sqlite3_close(source) == SQLITE_OK && sqlite3_close(dest) == SQLITE_OK, "backup close");
    puts("PASS backup: rows=1 value=42");
    return 0;
}
