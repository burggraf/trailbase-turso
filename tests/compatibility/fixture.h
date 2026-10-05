#ifndef SPIKE_FIXTURE_H
#define SPIKE_FIXTURE_H
#define _GNU_SOURCE
#include <dlfcn.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include "sqlite3.h"

/* Check the actual runtime image, not just a successful link. */
static int engine_check(void) {
    struct rlimit no_core = {0, 0};
    (void)setrlimit(RLIMIT_CORE, &no_core);
    Dl_info info;
    char actual[PATH_MAX], expected[PATH_MAX];
    const char *want = getenv("EXPECTED_ENGINE_LIBRARY");
    if (!dladdr((void *)sqlite3_open, &info) || !info.dli_fname) {
        fprintf(stderr, "cannot identify engine image\n");
        return 90;
    }
    /* System SQLite may live only in macOS's shared cache, not on disk.
     * The explicitly selected Turso image MUST have a real on-disk path. */
    printf("ENGINE_LIBRARY=%s\n", info.dli_fname);
    fflush(stdout);
    if (want && (!realpath(info.dli_fname, actual) || !realpath(want, expected) || strcmp(actual, expected))) {
        fprintf(stderr, "engine image mismatch: wanted %s, loaded %s\n", want, info.dli_fname);
        return 90;
    }
    return 0;
}

static void require(int ok, const char *what) {
    if (!ok) {
        fprintf(stderr, "fixture assertion failed: %s\n", what);
        exit(10);
    }
}

static sqlite3_stmt *prepare(sqlite3 *db, const char *sql) {
    sqlite3_stmt *stmt = NULL;
    require(sqlite3_prepare_v2(db, sql, -1, &stmt, NULL) == SQLITE_OK, sql);
    return stmt;
}

static void execute(sqlite3 *db, const char *sql) {
    sqlite3_stmt *stmt = prepare(db, sql);
    require(sqlite3_step(stmt) == SQLITE_DONE, sql);
    require(sqlite3_finalize(stmt) == SQLITE_OK, "finalize");
}
#endif
