SELECT count(*)
FROM cast_info, company_name, complete_cast, movie_companies, movie_keyword, name, title
WHERE name.imdb_index = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.movie_id = title.id;
