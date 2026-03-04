#include <stdio.h>
#include <string.h>

int print(int value) {
    printf("%d\n", value);
    return 0;
}

int print_str(const char *value) {
    printf("%s\n", value);
    return 0;
}

int print_float(double value) {
    printf("%f\n", value);
    return 0;
}

const char *read_line() {
    static char buffer[256];
    if (fgets(buffer, sizeof(buffer), stdin) == NULL) {
        buffer[0] = '\0';
        return buffer;
    }
    size_t len = strlen(buffer);
    if (len > 0 && buffer[len - 1] == '\n') {
        buffer[len - 1] = '\0';
    }
    return buffer;
}

const char *format1(const char *template, const char *arg) {
    static char buffer[512];
    const char *placeholder = strstr(template, "{}");
    if (placeholder == NULL) {
        snprintf(buffer, sizeof(buffer), "%s", template);
        return buffer;
    }
    size_t prefix_len = (size_t)(placeholder - template);
    snprintf(
        buffer,
        sizeof(buffer),
        "%.*s%s%s",
        (int)prefix_len,
        template,
        arg,
        placeholder + 2
    );
    return buffer;
}
