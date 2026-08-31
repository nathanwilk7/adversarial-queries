SET join_collapse_limit = 1;
SELECT count(*)
FROM ((((movie_companies CROSS JOIN (title CROSS JOIN complete_cast)) CROSS JOIN cast_info) CROSS JOIN movie_keyword) CROSS JOIN company_name) CROSS JOIN name
WHERE name.imdb_index = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.movie_id = title.id;
