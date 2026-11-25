'use strict';
const paths = {
  map:'m3 5 6-2 6 2 6-2v16l-6 2-6-2-6 2z M9 3v16 M15 5v16',
  layers:'m3 8 9-5 9 5-9 5z M3 12l9 5 9-5 M3 16l9 5 9-5',
  box:'m3 7 9-5 9 5v10l-9 5-9-5z M3 7l9 5 9-5 M12 12v10 M7.5 4.5l9 5',
  route:'M5 18v-5a3 3 0 0 1 3-3h8a3 3 0 0 0 3-3V5 M2 16l3 3 3-3 M16 7l3-3 3 3',
  receipt:'M5 3h14v18l-3-2-4 2-4-2-3 2z M8 7h8 M8 11h6 M8 15h4',
  chart:'M4 3v17h17 M8 15v-4 M13 15V6 M18 15V9',
  activity:'M2 12h5l3-8 4 16 3-8h5',
  play:'m8 4 12 8-12 8z',
  clock:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z M12 7v5l4 2',
  person:'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0z M4 21v-2a8 8 0 0 1 16 0v2',
  contract:'M6 2h9l4 4v16H6z M14 2v5h5 M9 11h7 M9 15h6',
  filter:'M3 6h8m4 0h6 M3 12h3m4 0h11 M3 18h11m4 0h3 M11 3v6 M6 9v6 M14 15v6',
  pin:'M19 9c0 5-7 12-7 12S5 14 5 9a7 7 0 0 1 14 0z M14.5 9a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0z',
  arrow:'M4 12h15 M14 6l6 6-6 6',
  truck:'M3 5h12v12H3z M15 10h4l3 4v3h-7 M9 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0z M20 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0z',
  hub:'M2 10l10-7 10 7 M4 10v11h16V10 M8 21v-8h8v8 M8 16h8',
  wallet:'M3 6a2 2 0 0 1 2-2h13v4 M3 6v13a1 1 0 0 0 1 1h16V8H5a2 2 0 0 1-2-2z M20 12h-5v4h5',
  check:'m4 12 5 5L20 6',chevron:'m9 5 7 7-7 7',down:'m6 9 6 6 6-6',
  plus:'M12 4v16 M4 12h16',minus:'M4 12h16',close:'m5 5 14 14 M19 5 5 19',
  fit:'M9 3H3v6 M15 3h6v6 M21 15v6h-6 M9 21H3v-6',
  list:'M8 6h13 M8 12h13 M8 18h13 M3 6h1 M3 12h1 M3 18h1',
  calendar:'M4 5h16v16H4z M4 10h16 M8 2v6 M16 2v6',refresh:'M20 10a8 8 0 1 0-1.5 8 M20 4v6h-6',
  scan:'M3 8V3h5 M16 3h5v5 M21 16v5h-5 M8 21H3v-5 M4 12h16',
  trend:'m3 16 6-6 4 4 8-9 M15 5h6v6',info:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z M12 11v6 M12 7v1',
  download:'M12 3v12 M7 10l5 5 5-5 M4 17v4h16v-4',target:'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0z',
  timebox:'M4 3h16v5l-5 4 5 4v5H4v-5l5-4-5-4z',switch:'M3 7h16m-4-4 4 4-4 4 M21 17H5m4-4-4 4 4 4'
};
function icon(name, size=18) {
  return '<svg aria-hidden="true" width="'+size+'" height="'+size+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="'+(paths[name]||paths.box)+'"/></svg>';
}
