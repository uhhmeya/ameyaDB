#define _GNU_SOURCE
#include "LOL.h"
#include <sched.h>
#include <time.h>
#include <sys/wait.h>

#define PREAMBLE 0xAA
#define MSGLEN 500

static void pin(int cpu) {
    cpu_set_t set; CPU_ZERO(&set); CPU_SET(cpu, &set);
    sched_setaffinity(0, sizeof(set), &set);
}

static void send(void *line[LINES], uint8_t byte) {
    for (;;) {
        for (int r = 0; r < REPS; r++) {
            for (int b = 0; b < 8; b++)
                if (byte & (1 << b)) maccess(line[1 + b]);
            maccess(line[REQ]);
        }
        if (sense(line[ACK])) break;
    }
    int lo = 0;
    while (lo < DEB)
        lo = sense(line[ACK]) ? 0 : lo + 1;
}

static uint8_t receive(void *line[LINES]) {
    for (;;) {
        for (int b = 0; b < 8; b++) flush(line[1 + b]);
        if (sense(line[REQ])) break;
    }
    int vote[8] = {0};
    for (int k = 0; k < VOTES; k++) {
        for (int b = 0; b < 8; b++) flush(line[1 + b]);
        for (volatile int d = 0; d < 300; d++);
        for (int b = 0; b < 8; b++)
            if (reload(line[1 + b]) < THRESHOLD) vote[b]++;
    }
    uint8_t byte = 0;
    for (int b = 0; b < 8; b++)
        if (vote[b] * 2 > VOTES) byte |= (1 << b);
    int lo = 0;
    while (lo < DEB) {
        for (int r = 0; r < REPS; r++) maccess(line[ACK]);
        lo = sense(line[REQ]) ? 0 : lo + 1;
    }
    return byte;
}

int main(void) {
    void *line[LINES];
    map_lines(line);

    static uint8_t msg[MSGLEN], got[MSGLEN];
    for (int i = 0; i < MSGLEN; i++) msg[i] = (uint8_t)(i * 137 + 29);

    pid_t pid = fork();
    if (pid == 0) {
        pin(4);
        send(line, PREAMBLE);
        for (int i = 0; i < MSGLEN; i++) send(line, msg[i]);
        _exit(0);
    }
    pin(2);

    while (receive(line) != PREAMBLE);
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    for (int i = 0; i < MSGLEN; i++) got[i] = receive(line);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    wait(NULL);

    double sec = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
    int byteerr = 0, biterr = 0;
    for (int i = 0; i < MSGLEN; i++) {
        if (got[i] != msg[i]) byteerr++;
        biterr += __builtin_popcount(got[i] ^ msg[i]);
    }

    printf("bytes sent       : %d\n", MSGLEN);
    printf("elapsed          : %.6f s\n", sec);
    printf("interval per byte: %.2f us\n", sec / MSGLEN * 1e6);
    printf("rate             : %.1f bytes/s  (%.3f KB/s)\n", MSGLEN / sec, MSGLEN / sec / 1024);
    printf("byte error rate  : %d / %d  (%.2f%%)\n", byteerr, MSGLEN, 100.0 * byteerr / MSGLEN);
    printf("bit error rate   : %d / %d  (%.2f%%)\n", biterr, MSGLEN * 8, 100.0 * biterr / (MSGLEN * 8));
    return 0;
}