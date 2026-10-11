/**
 * webpack 配置。
 *
 * 两种模式：
 *   - `npm run dev`  → webpack-dev-server（devServer 段，代理到 Django:8000）；
 *   - `npm run build`→ `webpack --mode production`（CLI 的 mode 覆盖下面的 "development"，
 *     开启 Terser 压缩、去掉 devtool）。
 *
 * 体积 / 首屏预算（2026-10 实测线上 staticfiles，非估算）：
 *   修复前：`vendor.*.js` 单块 5.79MB，全部第三方库（survey-creator / tiptap / mammoth /
 *   docx-preview / chart.js / frappe-gantt …）都在里面 —— 因为 cacheGroup 用了
 *   `chunks: "all"`，异步页面的重库也被拽进首屏，任何页面都要先把 5.79MB 下完。
 *   修复后：只有「首屏同步 import 的第三方库」进 vendor，其余随页面 chunk 按需下载。
 *   验收口径：构建输出里的 asset 体积列表（CI 的 frontend job summary 也会打印 dist 体积）。
 */
const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const CopyWebpackPlugin = require("copy-webpack-plugin");

module.exports = {
  // 仅对 dev-server 生效；生产构建由 CLI 的 --mode production 覆盖。
  mode: "development",
  entry: "./src/index.tsx",
  output: {
    path: path.resolve(__dirname, "dist"),
    // [contenthash]：文件名含 20 位十六进制，nginx 对这类产物给 1 年 immutable 缓存
    // （见 scripts/install.sh 写的 location 正则），所以产物命名规则改动要与 nginx 同步。
    filename: "[name].[contenthash].js",
    chunkFilename: "[name].[contenthash].chunk.js",
    publicPath: "/static/",
    clean: true,
  },
  resolve: {
    extensions: [".ts", ".tsx", ".js", ".jsx"],
  },
  // 编译缓存：只影响本地 / CI 的重建速度，不影响产物内容。
  cache: { type: "filesystem" },
  module: {
    rules: [
      {
        test: /\.tsx?$/,
        use: {
          loader: "ts-loader",
          options: { onlyCompileBundledFiles: true },
        },
        exclude: /node_modules/,
      },
      {
        // 样式经 style-loader 注入 <style>（不单独产出 .css 文件，故无需 MiniCssExtract）。
        test: /\.css$/,
        use: ["style-loader", "css-loader"],
      },
    ],
  },
  plugins: [
    new HtmlWebpackPlugin({
      template: "./template.html",
      favicon: "./public/favicon.ico",
    }),
    new CopyWebpackPlugin({
      patterns: [
        {
          // 看板娘（Live2D）运行期懒加载：模型与 widget 按需从 /static/live2d/ 取，
          // 体积大但不在首屏路径上，故整目录直拷而不进 bundle。
          from: path.resolve(__dirname, "vendor/live2d"),
          to: "live2d",
        },
      ],
    }),
  ],
  optimization: {
    // 运行时代码单独成块：改业务代码只让 runtime 的 hash 变化，vendor / app 不连坐，
    // 「发布一次全量重下」变成「只重下变了的那个文件」。
    runtimeChunk: "single",
    // 稳定 id：跨发布保持同一模块的 chunk 归属与命名，长缓存才能命中。
    moduleIds: "deterministic",
    chunkIds: "deterministic",
    splitChunks: {
      chunks: "all",
      // 小于 20KB 的共享模块不值得单独成块（多发一个请求的代价 > 省下的字节）。
      minSize: 20 * 1024,
      maxInitialRequests: 8,
      cacheGroups: {
        // ① 首屏必需：同步 import 的第三方库合成一个 vendor。
        //    `chunks: "initial"` 是这里的关键——它把「只被异步页面用到」的库挡在这个组外。
        //    注意 l2d（Live2D 引擎）被显式排除，永不进首屏。
        vendor: {
          test: /[\\/]node_modules[\\/](?!l2d(?:$|[\\/]))/,
          name: "vendor",
          chunks: "initial",
          priority: 40,
        },
        // ② 异步页面之间共享的第三方库：>=2 个页面用到才抽出来，避免同一个库在每个
        //    页面 chunk 里各存一份。不指定 name → 交给 webpack 按模块分组命名。
        asyncVendor: {
          test: /[\\/]node_modules[\\/]/,
          chunks: "async",
          minChunks: 2,
          priority: 30,
          reuseExistingChunk: true,
        },
        // ③ 应用代码里被 >=2 个异步页面共享的模块（组件 / 工具），保留 webpack 默认组的
        //    行为，避免重复打包。
        default: {
          minChunks: 2,
          priority: 10,
          reuseExistingChunk: true,
        },
        // 关掉默认的 node_modules 大组：它会把所有第三方库重新并成一块，
        // 等于撤销 ① 的隔离效果（这正是修复前 5.79MB 单块的成因）。
        defaultVendors: false,
      },
    },
  },
  devServer: {
    port: 3000,
    hot: true,
    historyApiFallback: { index: "/static/index.html" },
    proxy: [
      { context: ["/ws/messaging", "/ws/exam-board"], target: "http://localhost:8000", ws: true },
      { context: ["/auth", "/admin", "/media", "/tasks", "/messaging", "/news", "/attachments", "/uploads", "/activities", "/reviews", "/about", "/exam_board", "/tutorials", "/recruitment", "/site-policy", "/panorama"], target: "http://localhost:8000" },
    ],
  },
};
