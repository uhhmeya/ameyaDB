#define _GNU_SOURCE
#include "LOL.h"
#include <sched.h>
#include <signal.h>
#include <sys/wait.h>

static void pin(int cpu) {
    cpu_set_t set; CPU_ZERO(&set); CPU_SET(cpu, &set);
    sched_setaffinity(0, sizeof(set), &set);
}

int main(void) {
    void *line[LINES];
    map_lines(line);

    pid_t pid = fork();
    if (pid == 0) {
        pin(4);
        for (;;) maccess(line[0]);
        _exit(0);
    }
    pin(2);

    int N = 20000;
    long present[8] = {0}, absent[8] = {0};
    unsigned long pmin = ~0UL, amin = ~0UL;
    for (int i = 0; i < N; i++) {
        flush(line[0]); for (volatile int d = 0; d < 500; d++); unsigned long t = reload(line[0]);
        if (t < pmin) pmin = t;
        present[t<60?0:t<100?1:t<140?2:t<180?3:t<220?4:t<260?5:t<300?6:7]++;
        flush(line[8]); for (volatile int d = 0; d < 500; d++); unsigned long u = reload(line[8]);
        if (u < amin) amin = u;
        absent[u<60?0:u<100?1:u<140?2:u<180?3:u<220?4:u<260?5:u<300?6:7]++;
    }
    kill(pid, SIGKILL); wait(NULL);

    const char *L[8] = {"<60","<100","<140","<180","<220","<260","<300",">=300"};
    printf("bucket   PRESENT(line0)   ABSENT(line8)\n");
    for (int i = 0; i < 8; i++) printf("%7s  %12ld  %12ld\n", L[i], present[i], absent[i]);
    printf("present min=%lu  absent min=%lu\n", pmin, amin);
    return 0;
}