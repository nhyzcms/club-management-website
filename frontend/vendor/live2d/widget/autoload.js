/*!
 * Live2D Widget - Localized Version
 * https://github.com/stevenjoezhang/live2d-widget
 */

// 【重要】请根据你 CMS 前端静态资源的实际挂载路径修改此处
// 例如：如果 live2d 文件夹在 /static/vendor/live2d/，则改为 '/static/vendor/live2d/'
const live2d_path = '/vendor/live2d/';

// 封装异步加载资源的方法
function loadExternalResource(url, type) {
  return new Promise((resolve, reject) => {
    let tag;

    if (type === 'css') {
      tag = document.createElement('link');
      tag.rel = 'stylesheet';
      tag.href = url;
    }
    else if (type === 'js') {
      tag = document.createElement('script');
      tag.type = 'module'; // 新版 SDK 需要 module 类型
      tag.src = url;
    }
    
    if (tag) {
      tag.onload = () => resolve(url);
      tag.onerror = () => reject(url);
      document.head.appendChild(tag);
    }
  });
}

(async () => {
  // 可选：根据屏幕宽度判断是否加载（手机端通常建议隐藏以节省性能）
  // if (screen.width < 768) return;

  // 避免图片资源跨域问题（CORS）
  const OriginalImage = window.Image;
  window.Image = function(...args) {
    const img = new OriginalImage(...args);
    img.crossOrigin = "anonymous";
    return img;
  };
  window.Image.prototype = OriginalImage.prototype;

  // 加载 waifu.css 和 waifu-tips.js
  await Promise.all([
    loadExternalResource(live2d_path + 'widget/waifu.css', 'css'),
    loadExternalResource(live2d_path + 'widget/waifu-tips.js', 'js')
  ]);

  // 初始化看板娘
  initWidget({
    // 模型列表文件路径（即我们创建的 model_list.json）
    waifuPath: live2d_path + 'model_list.json',
    
    // 静态资源基础路径（用于加载模型贴图、动作等）
    cdnPath: live2d_path + 'models/',
    
    // Cubism 2 核心库路径（兼容旧模型）
    cubism2Path: live2d_path + 'runtime/live2d.min.js',
    
    // Cubism 4/5 核心库路径（支持新模型，已改为本地路径）
    cubism5Path: live2d_path + 'runtime/live2dcubismcore.min.js',
    
    // 工具栏功能：切换模型、切换纹理、拍照、信息、关闭
    tools: ['switch-model', 'switch-texture', 'photo', 'info', 'quit'],
    
    // 日志级别
    logLevel: 'warn',
    
    // 是否允许拖拽
    drag: true,
  });
})();

console.log(`\n%cLive2D%cWidget%c Loaded Locally\n`, 'padding: 8px; background: #cd3e45; font-weight: bold; color: white;', 'padding: 8px; background: #ff5450; color: #eee;', '');

console.log(`\n%cLive2D%cWidget%c\n`, 'padding: 8px; background: #cd3e45; font-weight: bold; font-size: large; color: white;', 'padding: 8px; background: #ff5450; font-size: large; color: #eee;', '');

/*
く__,.ヘヽ.        /  ,ー､ 〉
         ＼ ', !-─‐-i  /  /´
         ／｀ｰ'       L/／｀ヽ､
       /   ／,   /|   ,   ,       ',
     ｲ   / /-‐/  ｉ  L_ ﾊ ヽ!   i
      ﾚ ﾍ 7ｲ｀ﾄ   ﾚ'ｧ-ﾄ､!ハ|   |
        !,/7 '0'     ´0iソ|    |
        |.从"    _     ,,,, / |./    |
        ﾚ'| i＞.､,,__  _,.イ /   .i   |
          ﾚ'| | / k_７_/ﾚ'ヽ,  ﾊ.  |
            | |/i 〈|/   i  ,.ﾍ |  i  |
           .|/ /  ｉ：    ﾍ!    ＼  |
            kヽ>､ﾊ    _,.ﾍ､    /､!
            !'〈//｀Ｔ´', ＼ ｀'7'ｰr'
            ﾚ'ヽL__|___i,___,ンﾚ|ノ
                ﾄ-,/  |___./
                'ｰ'    !_,.:
*/
