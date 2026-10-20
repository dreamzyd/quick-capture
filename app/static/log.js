(function () {
  'use strict';
  var LEVEL_LABEL = { 0: '没守住', 25: '勉强', 50: '一半', 75: '基本守住', 100: '稳' };
  var TODAY = document.body.dataset.today;
  var groupsEl = document.getElementById('groups');
  var emptyEl = document.getElementById('empty');
  var countEl = document.getElementById('count');
  var toastEl = document.getElementById('toast');
  var toastText = document.getElementById('toast-text');
  var undoBtn = document.getElementById('undo');
  var lastAddedId = null;
  var toastTimer = null;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function timeOf(iso) { return String(iso || '').slice(11, 16); }
  function setCount(delta) {
    var n = parseInt(countEl.textContent, 10) || 0;
    countEl.textContent = Math.max(0, n + delta);
  }
  function showToast(text, undoable) {
    toastText.textContent = text;
    undoBtn.style.display = undoable ? '' : 'none';
    toastEl.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove('show'); }, undoable ? 5000 : 2200);
  }

  function todayList() {
    var g = groupsEl.querySelector('.day-group[data-day="' + TODAY + '"]');
    if (!g) {
      g = document.createElement('div');
      g.className = 'day-group';
      g.dataset.day = TODAY;
      g.innerHTML = '<div class="list-head"><span class="day">今天</span><span>点一行可改档位或补一句</span></div><ul class="rows"></ul>';
      groupsEl.insertBefore(g, groupsEl.firstChild);
      emptyEl.style.display = 'none';
    }
    return g.querySelector('ul.rows');
  }

  function makeRow(it) {
    var li = document.createElement('li');
    li.className = 'row';
    li.dataset.id = it.id;
    li.dataset.level = it.level;
    li.dataset.note = it.note || '';
    li.dataset.created = it.created_at || '';
    li.innerHTML =
      '<span class="time">' + timeOf(it.created_at) + '</span>' +
      '<span class="chip">' + it.level + '</span>' +
      '<span class="body"><span class="note' + (it.note ? '' : ' addnote') + '">' +
      (it.note ? esc(it.note) : '＋写一句') + '</span></span>';
    return li;
  }

  function addLevel(level) {
    fetch('/log/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ level: level }),
      credentials: 'same-origin'
    }).then(function (r) { return r.json().catch(function () { return {}; }); })
      .then(function (data) {
        if (!data || !data.ok) { showToast('没存上，再点一次'); return; }
        var list = todayList();
        list.insertBefore(makeRow(data.item), list.firstChild);
        emptyEl.style.display = 'none';
        lastAddedId = data.item.id;
        setCount(1);
        showToast('已记 ' + level + ' · ' + (LEVEL_LABEL[level] || ''), true);
      })
      .catch(function () { showToast('没存上，检查网络'); });
  }

  document.getElementById('levels').addEventListener('click', function (e) {
    var btn = e.target.closest('.lv');
    if (btn) addLevel(parseInt(btn.dataset.lv, 10));
  });

  undoBtn.addEventListener('click', function () {
    if (!lastAddedId) return;
    var id = lastAddedId;
    fetch('/log/' + id + '/delete', { method: 'POST', credentials: 'same-origin' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data && data.ok) {
          var row = groupsEl.querySelector('[data-id="' + id + '"]');
          if (row) row.remove();
          setCount(-1);
          showToast('已撤销', false);
        } else { showToast('撤销失败'); }
      });
    lastAddedId = null;
  });

  function openEditor(row) {
    var id = row.dataset.id;
    var level = parseInt(row.dataset.level, 10);
    var note = row.dataset.note || '';
    var createdAt = row.dataset.created || '';
    var box = document.createElement('li');
    box.className = 'editor';
    var chips = '';
    [0, 25, 50, 75, 100].forEach(function (v) {
      chips += '<button type="button" data-lv="' + v + '"' + (v === level ? ' class="on"' : '') + '>' + v + '</button>';
    });
    box.innerHTML =
      '<div class="lvrow">' + chips + '</div>' +
      '<textarea maxlength="2000" placeholder="补一句（可不填）">' + esc(note) + '</textarea>' +
      '<div class="acts">' +
      '<button type="button" class="del">删除</button>' +
      '<button type="button" class="cancel">取消</button>' +
      '<button type="button" class="save">保存</button>' +
      '</div>';
    row.parentNode.replaceChild(box, row);
    var current = level;
    box.querySelector('.lvrow').addEventListener('click', function (e) {
      var b = e.target.closest('button[data-lv]');
      if (!b) return;
      current = parseInt(b.dataset.lv, 10);
      box.querySelectorAll('.lvrow button').forEach(function (x) { x.classList.toggle('on', x === b); });
    });
    box.querySelector('.cancel').addEventListener('click', function () {
      box.parentNode.replaceChild(makeRow({ id: id, level: level, note: note, created_at: createdAt }), box);
    });
    box.querySelector('.save').addEventListener('click', function () {
      var text = box.querySelector('textarea').value.slice(0, 2000);
      fetch('/log/' + id + '/update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ level: current, note: text }),
        credentials: 'same-origin'
      }).then(function (r) { return r.json(); }).then(function (data) {
        if (!data || !data.ok) { showToast('保存失败'); return; }
        box.parentNode.replaceChild(makeRow(data.item), box);
        showToast('已保存', false);
      });
    });
    box.querySelector('.del').addEventListener('click', function () {
      fetch('/log/' + id + '/delete', { method: 'POST', credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).then(function (data) {
          if (data && data.ok) {
            var group = box.closest('.day-group');
            box.remove();
            if (group && group.dataset.day === TODAY) setCount(-1);
            showToast('已删除', false);
          } else { showToast('删除失败'); }
        });
    });
  }

  groupsEl.addEventListener('click', function (e) {
    var row = e.target.closest('.row');
    if (row) openEditor(row);
  });

  document.addEventListener('keydown', function (e) {
    var t = e.target.tagName;
    if (t === 'TEXTAREA' || t === 'INPUT' || e.metaKey || e.ctrlKey || e.altKey) return;
    var map = { '1': 0, '2': 25, '3': 50, '4': 75, '5': 100 };
    if (map[e.key] !== undefined) { e.preventDefault(); addLevel(map[e.key]); }
  });
})();
