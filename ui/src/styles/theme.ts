import type { ThemeConfig } from "antd";

export const theme: ThemeConfig = {
  algorithm: undefined,
  token: {
    colorPrimary: "#5B8CFF",
    colorSuccess: "#2DD4A8",
    colorWarning: "#F6C85F",
    colorError: "#FF6B7A",
    colorBgBase: "#0B1020",
    colorBgContainer: "#121A2B",
    colorBorder: "#24324A",
    colorText: "#E8EEF8",
    colorTextSecondary: "#93A4BD",
    borderRadius: 8,
    controlHeight: 36,
    fontFamily:
      '"Inter", "SF Pro Display", "PingFang SC", "Microsoft YaHei", sans-serif'
  },
  components: {
    Layout: {
      bodyBg: "#0B1020",
      headerBg: "rgba(11, 16, 32, .84)",
      siderBg: "#0E1525"
    },
    Menu: {
      darkItemBg: "#0E1525",
      itemBg: "#0E1525",
      itemSelectedBg: "rgba(91, 140, 255, .16)",
      itemSelectedColor: "#8EAEFF",
      itemColor: "#93A4BD"
    },
    Table: {
      headerBg: "#0F1728",
      rowHoverBg: "#172238",
      borderColor: "#24324A"
    }
  }
};
