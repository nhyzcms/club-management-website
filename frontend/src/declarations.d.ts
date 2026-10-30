declare module "*.css" {
  const content: string;
  export default content;
}

// webpack `asset/resource`：.wasm 导出的是产物 URL（含 contenthash）。
// 条码解码器用它做 locateFile，把 zxing 的 wasm 指到自托管副本。
declare module "*.wasm" {
  const url: string;
  export default url;
}
