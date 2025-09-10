const data = [
  {
    season: "2023/2024",
    matches: [
      { date: "2024-01-15", team1: "Team A", team2: "Team B", score: "2-1" },
      { date: "2024-01-20", team1: "Team C", team2: "Team D", score: "1-1" }
    ]
  },
  {
    season: "2022/2023",
    matches: [
      { date: "2023-02-10", team1: "Team E", team2: "Team F", score: "3-0" },
      { date: "2023-03-05", team1: "Team G", team2: "Team H", score: "0-2" }
    ]
  }
];

// Elementy HTML
const seasonFilter = document.getElementById('seasonFilter');
const resultsTable = document.querySelector('#resultsTable tbody');

// Wypełnij listę sezonów
data.forEach(season => {
  const option = document.createElement('option');
  option.value = season.season;
  option.textContent = season.season;
  seasonFilter.appendChild(option);
});

// Wyświetl mecze dla wybranego sezonu
const displayMatches = (season) => {
  resultsTable.innerHTML = ''; // Wyczyść tabelę
  const matches = data.find(s => s.season === season)?.matches || [];
  matches.forEach(match => {
    const row = `
      <tr>
        <td>${match.date}</td>
        <td>${match.team1}</td>
        <td>${match.team2}</td>
        <td>${match.score}</td>
      </tr>`;
    resultsTable.innerHTML += row;
  });
};

// Obsługa zmiany sezonu
seasonFilter.addEventListener('change', (e) => {
  displayMatches(e.target.value);
});

// Domyślnie pokaż pierwszy sezon
if (data.length > 0) {
  displayMatches(data[0].season);
  seasonFilter.value = data[0].season;
}