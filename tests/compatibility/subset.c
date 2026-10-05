#include "fixture.h"

int main(int argc, char **argv) {
    int rc = engine_check();
    if (rc) return rc;
    require(argc == 2, "database path argument");
    sqlite3 *db = NULL;
    require(sqlite3_open(argv[1], &db) == SQLITE_OK, "open");
    execute(db, "CREATE TABLE values_control (id INTEGER PRIMARY KEY, i INTEGER, r REAL, t TEXT, b BLOB, n TEXT)");
    execute(db, "BEGIN");
    sqlite3_stmt *stmt = prepare(db, "INSERT INTO values_control VALUES (1, ?1, ?2, ?3, ?4, ?5)");
    const unsigned char blob[] = {0, 1, 255};
    const char text[] = "hello\xc3\xa9";
    require(sqlite3_bind_int64(stmt, 1, INT64_C(9007199254740993)) == SQLITE_OK, "bind int64");
    require(sqlite3_bind_double(stmt, 2, 1.25) == SQLITE_OK, "bind real");
    /* SQLITE_STATIC is sufficient: these buffers outlive the statement. */
    require(sqlite3_bind_text(stmt, 3, text, (int)sizeof(text) - 1, NULL) == SQLITE_OK, "bind text");
    require(sqlite3_bind_blob(stmt, 4, blob, (int)sizeof(blob), NULL) == SQLITE_OK, "bind blob");
    require(sqlite3_bind_null(stmt, 5) == SQLITE_OK, "bind null");
    require(sqlite3_step(stmt) == SQLITE_DONE, "insert");
    require(sqlite3_finalize(stmt) == SQLITE_OK, "finalize insert");
    execute(db, "COMMIT");
    execute(db, "BEGIN");
    execute(db, "UPDATE values_control SET t = 'rolled back' WHERE id = 1");
    execute(db, "INSERT INTO values_control (id) VALUES (2)");
    execute(db, "ROLLBACK");
    require(sqlite3_close(db) == SQLITE_OK, "close before reopen");
    require(sqlite3_open(argv[1], &db) == SQLITE_OK, "reopen");
    stmt = prepare(db, "SELECT i, r, t, b, n FROM values_control ORDER BY id");
    require(sqlite3_step(stmt) == SQLITE_ROW, "read row");
    require(sqlite3_column_type(stmt, 0) == SQLITE_INTEGER && sqlite3_column_int64(stmt, 0) == INT64_C(9007199254740993), "integer roundtrip");
    require(sqlite3_column_type(stmt, 1) == SQLITE_FLOAT && sqlite3_column_double(stmt, 1) == 1.25, "real roundtrip");
    require(sqlite3_column_type(stmt, 2) == SQLITE_TEXT && sqlite3_column_bytes(stmt, 2) == (int)sizeof(text) - 1 && memcmp(sqlite3_column_text(stmt, 2), text, sizeof(text) - 1) == 0, "text and rollback");
    require(sqlite3_column_type(stmt, 3) == SQLITE_BLOB && sqlite3_column_bytes(stmt, 3) == (int)sizeof(blob) && memcmp(sqlite3_column_blob(stmt, 3), blob, sizeof(blob)) == 0, "blob roundtrip");
    require(sqlite3_column_type(stmt, 4) == SQLITE_NULL, "null roundtrip");
    require(sqlite3_step(stmt) == SQLITE_DONE, "rollback removed second row");
    require(sqlite3_finalize(stmt) == SQLITE_OK, "finalize read");
    require(sqlite3_close(db) == SQLITE_OK, "close");
    puts("PASS subset: integer=9007199254740993 real=1.25 text=utf8 blob=0001ff null=NULL rows=1 commit=visible-after-reopen rollback=unchanged");
    return 0;
}
