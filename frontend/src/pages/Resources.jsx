import { useEffect, useState } from "react";
import { api } from "../api";

export default function Resources() {
  const [rooms, setRooms] = useState([]);
  const [teachers, setTeachers] = useState([]);
  const [chains, setChains] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    Promise.all([api.rooms(), api.teachers(), api.substituteChains()])
      .then(([r, t, c]) => {
        setRooms(r);
        setTeachers(t);
        setChains(c);
      })
      .catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="msg err">{err}</div>;

  // 按主执行器归并替身链，position 已由后端按优先级排序
  const chainByPrimary = new Map();
  for (const c of chains) {
    if (!chainByPrimary.has(c.primary_code)) chainByPrimary.set(c.primary_code, []);
    chainByPrimary.get(c.primary_code).push(c);
  }

  return (
    <>
      <section className="panel">
        <h2>算力槽</h2>
        <table>
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th>容量</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {rooms.map((r) => (
              <tr key={r.code}>
                <td>{r.code}</td>
                <td>{r.name}</td>
                <td>{r.capacity}</td>
                <td>{r.active ? "启用" : "停用"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="panel">
        <h2>执行器（能力标签）</h2>
        <table>
          <thead>
            <tr>
              <th>编码</th>
              <th>名称</th>
              <th>作业类型能力</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {teachers.map((t) => (
              <tr key={t.code}>
                <td>{t.code}</td>
                <td>{t.name}</td>
                <td>{t.subject}</td>
                <td>{t.active ? "启用" : "停用"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section className="panel">
        <h2>替身优先级表</h2>
        <table>
          <thead>
            <tr>
              <th>主执行器</th>
              <th>替身链（按命中优先级）</th>
            </tr>
          </thead>
          <tbody>
            {[...chainByPrimary.entries()].map(([primary, links]) => (
              <tr key={primary}>
                <td>{primary}</td>
                <td>
                  {links.map((c) => (
                    <span
                      key={c.position}
                      className={`tag ${c.substitute_active ? "live" : "bad"}`}
                      style={{ marginRight: 6 }}
                      title={`能力：${c.substitute_subject}`}
                    >
                      #{c.position} {c.substitute_code} · {c.substitute_subject}
                    </span>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}
