SELECT count(*)
FROM cast_info, company_name, complete_cast, keyword, movie_companies, movie_keyword, movie_link, name, person_info, title
WHERE name.gender = 'm'
  AND title.production_year = 2009
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.person_id = name.id;
