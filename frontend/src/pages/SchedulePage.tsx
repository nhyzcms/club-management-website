// import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import AppShell from "../components/AppShell";

export default function SchedulePage() {
  const navigate = useNavigate();

  return (
    <AppShell>
      {/* 顶部头部 */}
      <div className="page-head">
        <div className="container">
          <nav className="breadcrumb">
            <a
              href="#"
              onClick={(e) => {
                e.preventDefault();
                navigate("/");
              }}
            >
              主页
            </a>
            <span className="sep">/</span>
            <span>课表下载</span>
          </nav>
          <div className="page-head-row">
            <div>
              <h1>课表下载</h1>
              <p className="section-sub">ClassIsland 及各班级课程表文件下载。</p>
            </div>
          </div>
        </div>
      </div>

      {/* 页面核心 */}
      <div className="container" style={{ paddingTop: 24, paddingBottom: 40 }}>
        <div style={{ backgroundColor: "var(--card-bg, #fff)", padding: "24px 32px", borderRadius: "8px" }}>
          <a href="/file/ClassIsland快速使用指南.pdf" download>
            <p>点击下载ClassIsland快速使用指南</p>
          </a>
          <h1>ClassIsland压缩包下载</h1>
          <a href="/file/ClassIsland.zip" download>
            <p>点击下载ClassIsland压缩包</p>
          </a>
          
          <h1> </h1>

          <h1>各班课程表文件下载</h1>

          <h2>高一年级</h2>
          <a href="/file/高一1.yml" download>
            <p>点击下载高一1班课程表文件</p>
          </a>
          <a href="/file/高一2.yml" download>
            <p>点击下载高一2班课程表文件</p>
          </a>
          <a href="/file/高一3.yml" download>
            <p>点击下载高一3班课程表文件</p>
          </a>
          <a href="/file/高一4.yml" download>
            <p>点击下载高一4班课程表文件</p>
          </a>
          <a href="/file/高一5.yml" download>
            <p>点击下载高一5班课程表文件</p>
          </a>
          <a href="/file/高一6.yml" download>
            <p>点击下载高一6班课程表文件</p>
          </a>
          <a href="/file/高一7.yml" download>
            <p>点击下载高一7班课程表文件</p>
          </a>
          <a href="/file/高一8.yml" download>
            <p>点击下载高一8班课程表文件</p>
          </a>
          <h1> </h1>
          
          <h2>高二年级</h2>
          <a href="/file/高二1.yml" download>
            <p>点击下载高二1班课程表文件</p>
          </a>
          <a href="/file/高二2.yml" download>
            <p>点击下载高二2班课程表文件</p>
          </a>
          <a href="/file/高二3.yml" download>
            <p>点击下载高二3班课程表文件</p>
          </a>
          <a href="/file/高二4.yml" download>
            <p>点击下载高二4班课程表文件</p>
          </a>
          <a href="/file/高二5.yml" download>
            <p>点击下载高二5班课程表文件</p>
          </a>
          <a href="/file/高二6.yml" download>
            <p>点击下载高二6班课程表文件</p>
          </a>
          <a href="/file/高二7.yml" download>
            <p>点击下载高二7班课程表文件</p>
          </a>
          <a href="/file/高二8.yml" download>
            <p>点击下载高二8班课程表文件</p>
          </a>
          <h1> </h1>


          <h2>高三年级</h2>
          <a href="/file/高三1.yml" download>
            <p>点击下载高三1班课程表文件</p>
          </a>
          <a href="/file/高三2.yml" download>
            <p>点击下载高三2班课程表文件</p>
          </a>
          <a href="/file/高三3.yml" download>
            <p>点击下载高三3班课程表文件</p>
          </a>
          <a href="/file/高三4.yml" download>
            <p>点击下载高三4班课程表文件</p>
          </a>
          <a href="/file/高三5.yml" download>
            <p>点击下载高三5班课程表文件</p>
          </a>
          <a href="/file/高三6.yml" download>
            <p>点击下载高三6班课程表文件</p>
          </a>
          <a href="/file/高三7.yml" download>
            <p>点击下载高三7班课程表文件</p>
          </a>
          <a href="/file/高三8.yml" download>
            <p>点击下载高三8班课程表文件</p>
          </a>
        </div>
      </div>
    </AppShell>
  );
}