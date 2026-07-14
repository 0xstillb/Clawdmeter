#include <cstdlib>
#include <cstring>
#include <iostream>

#include "usage_payload.h"

static void expect(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << std::endl;
        std::exit(1);
    }
}

static void expect_streq(const char* actual, const char* expected, const char* message) {
    if (std::strcmp(actual, expected) != 0) {
        std::cerr << message << "\nexpected: " << expected << "\nactual:   " << actual << std::endl;
        std::exit(1);
    }
}

static void test_legacy() {
    const char* json = R"json({"s":42,"sr":132,"w":17,"wr":5010,"st":"allowed","ok":true})json";
    UsageData data{};
    expect(usage_parse_json(json, &data), "legacy payload should parse");
    expect(data.valid, "legacy payload should mark data valid");
    expect(data.provider == USAGE_PROVIDER_CLAUDE, "legacy payload should default to Claude provider");
    expect_streq(data.mode, "legacy_flat", "legacy payload should use legacy_flat mode");
    expect_streq(data.top.label, "Current", "legacy top label should stay Current");
    expect(data.top.has_reset, "legacy top panel should use reset formatting");
    expect(data.top.pct == 42.0f, "legacy top pct should come from s");
    expect(data.top.reset_mins == 132, "legacy top reset should come from sr");
    expect_streq(data.bottom.label, "Weekly", "legacy bottom label should stay Weekly");
    expect(data.bottom.has_reset, "legacy bottom panel should use reset formatting");
    expect(data.bottom.pct == 17.0f, "legacy bottom pct should come from w");
    expect(data.bottom.reset_mins == 5010, "legacy bottom reset should come from wr");

    char buf[64];
    usage_panel_display_subtext(&data.top, buf, sizeof(buf));
    expect_streq(buf, "Resets in 2h 12m", "legacy top display text should be formatted from reset_mins");
}

static void test_provider_window() {
    const char* json = R"json({
      "p":"go",
      "mode":"window_window",
      "top":{"label":"Current","pct":55,"subtext":"Resets in 1h 40m","reset_mins":100,"kind":"window_short"},
      "bottom":{"label":"Weekly","pct":20,"subtext":"Resets in 4d 3h","reset_mins":5940,"kind":"window_long"},
      "st":"allowed",
      "ok":true
    })json";
    UsageData data{};
    expect(usage_parse_json(json, &data), "provider window payload should parse");
    expect(data.provider == USAGE_PROVIDER_GO, "provider should parse from p");
    expect_streq(data.mode, "window_window", "mode should parse from payload");
    expect_streq(data.top.label, "Current", "top label should parse from payload");
    expect_streq(data.bottom.label, "Weekly", "bottom label should parse from payload");
    expect(data.top.has_reset, "top panel should infer reset formatting from reset_mins");
    expect(data.bottom.has_reset, "bottom panel should infer reset formatting from reset_mins");

    char buf[64];
    usage_panel_display_subtext(&data.bottom, buf, sizeof(buf));
    expect_streq(buf, "Resets in 4d 3h", "window payload display text should use formatted reset text");
}

static void test_provider_claude_window() {
    const char* json = R"json({
      "p":"claude",
      "mode":"window",
      "top":{"label":"Current","pct":42,"reset_mins":120,"has_reset":true,"kind":"window_short"},
      "bottom":{"label":"Weekly","pct":17,"reset_mins":4320,"has_reset":true,"kind":"window_long"},
      "st":"allowed",
      "ok":true,
      "s":42,
      "sr":120,
      "w":17,
      "wr":4320
    })json";
    UsageData data{};
    expect(usage_parse_json(json, &data), "Claude provider payload should parse");
    expect(data.provider == USAGE_PROVIDER_CLAUDE, "provider should parse as Claude");
    expect_streq(data.mode, "window", "mode should remain canonical window");
    expect_streq(data.top.label, "Current", "Claude top label should stay Current");
    expect_streq(data.bottom.label, "Weekly", "Claude bottom label should stay Weekly");
    expect(data.top.has_reset, "Claude top panel should preserve reset semantics");
    expect(data.bottom.has_reset, "Claude bottom panel should preserve reset semantics");

    char buf[64];
    usage_panel_display_subtext(&data.top, buf, sizeof(buf));
    expect_streq(buf, "Resets in 2h 0m", "Claude top display text should format reset_mins");
}

static void test_provider_wallet_subtext() {
    const char* json = R"json({
      "p":"openrouter",
      "mode":"today_wallet",
      "top":{"label":"Today","pct":40,"subtext":"Resets in 10h 15m","reset_mins":615,"kind":"budget_daily"},
      "bottom":{"label":"Wallet","pct":75,"subtext":"$2.50 left / $10.00","kind":"wallet_depletion"},
      "st":"ok",
      "ok":true
    })json";
    UsageData data{};
    expect(usage_parse_json(json, &data), "provider wallet payload should parse");
    expect(data.provider == USAGE_PROVIDER_OPENROUTER, "provider should parse as openrouter");
    expect_streq(data.top.label, "Today", "top label should become Today");
    expect_streq(data.bottom.label, "Wallet", "bottom label should become Wallet");
    expect(data.top.has_reset, "top panel should still use reset formatting");
    expect(!data.bottom.has_reset, "wallet panel should preserve raw subtext");

    char buf[64];
    usage_panel_display_subtext(&data.bottom, buf, sizeof(buf));
    expect_streq(buf, "$2.50 left / $10.00", "wallet panel should show daemon-provided money text");
}

static void test_invalid_payload() {
    const char* json = R"json({"p":"openrouter","ok":true})json";
    UsageData data{};
    expect(!usage_parse_json(json, &data), "payload missing both legacy and provider panels should fail");
}

static void test_zen_prepaid() {
    const char* json = R"json({
      "p":"zen",
      "plan_type":"prepaid",
      "mode":"prepaid",
      "top":{"label":"Used","pct":0.79,"subtext":"$0.79","reset_mins":197,"has_reset":true,"kind":"budget_daily"},
      "bottom":{"label":"Remaining","pct":9.21,"subtext":"$9.21","reset_mins":0,"has_reset":false,"kind":"wallet_depletion"},
      "st":"allowed",
      "ok":true,
      "s":9.21,
      "sr":0,
      "w":0.36,
      "wr":197,
      "budget":10.0
    })json";
    UsageData data{};
    expect(usage_parse_json(json, &data), "Zen prepaid payload should parse");
    expect(data.valid, "Zen payload should mark data valid");
    expect(data.provider == USAGE_PROVIDER_ZEN, "provider should be Zen");
    expect_streq(data.plan_type, "prepaid", "plan_type should be prepaid");
    expect_streq(data.mode, "prepaid", "mode should be prepaid");
    expect_streq(data.top.label, "Used", "top label should be Used");
    expect_streq(data.bottom.label, "Remaining", "bottom label should be Remaining");
    expect_streq(data.top.kind, "budget_daily", "top kind should be budget_daily");
    expect_streq(data.bottom.kind, "wallet_depletion", "bottom kind should be wallet_depletion");
    expect(data.top.pct == 0.79f, "top pct should be 0.79 (total used)");
    expect(data.bottom.pct == 9.21f, "bottom pct should be 9.21 (raw dollar)");
    expect_streq(data.top.subtext, "$0.79", "top subtext should be raw dollar");
    expect_streq(data.bottom.subtext, "$9.21", "bottom subtext should show remaining");
    expect(data.budget == 10.0f, "budget should be parsed from payload");
}

static void test_codex_weekly_only() {
    const char* json = R"json({
      "p":"codex",
      "mode":"weekly_only",
      "top":{"label":"Weekly","pct":63,"reset_mins":4320,"has_reset":true,"kind":"window_long"},
      "bottom":{"label":"Unavailable","pct":0,"reset_mins":0,"has_reset":false,"subtext":"not applicable","kind":"hidden"},
      "st":"allowed",
      "ok":true,
      "s":63,
      "sr":4320,
      "w":63,
      "wr":4320
    })json";
    UsageData data{};
    expect(usage_parse_json(json, &data), "single-window Codex payload should parse");
    expect(data.provider == USAGE_PROVIDER_CODEX, "provider should be Codex");
    expect_streq(data.mode, "weekly_only", "mode should flag a single weekly limit");
    expect_streq(data.top.label, "Weekly", "top panel should be the weekly limit");
    expect(data.top.pct == 63.0f, "top panel should use the weekly remaining percent");
}

static void test_brightness_field() {
    uint8_t pct = 0;
    expect(usage_extract_brightness_pct(R"json({"brightness":75})json", &pct),
           "brightness field should parse");
    expect(pct == 75, "brightness should retain its valid percentage");
    expect(usage_extract_brightness_pct(R"json({"brightness":250})json", &pct),
           "out-of-range brightness should still parse");
    expect(pct == 100, "brightness should clamp above 100");
    expect(!usage_extract_brightness_pct(R"json({"brightness":"high"})json", &pct),
           "non-numeric brightness should be ignored");
}

int main(int argc, char** argv) {
    expect(argc == 2, "expected exactly one scenario argument");

    if (std::strcmp(argv[1], "legacy") == 0) {
        test_legacy();
    } else if (std::strcmp(argv[1], "provider_window") == 0) {
        test_provider_window();
    } else if (std::strcmp(argv[1], "provider_claude_window") == 0) {
        test_provider_claude_window();
    } else if (std::strcmp(argv[1], "provider_wallet_subtext") == 0) {
        test_provider_wallet_subtext();
    } else if (std::strcmp(argv[1], "invalid_payload") == 0) {
        test_invalid_payload();
    } else if (std::strcmp(argv[1], "zen_prepaid") == 0) {
        test_zen_prepaid();
    } else if (std::strcmp(argv[1], "codex_weekly_only") == 0) {
        test_codex_weekly_only();
    } else if (std::strcmp(argv[1], "brightness_field") == 0) {
        test_brightness_field();
    } else {
        std::cerr << "unknown scenario: " << argv[1] << std::endl;
        return 2;
    }

    return 0;
}
