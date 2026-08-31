SELECT count(*)
FROM aka_title, company_type, info_type, movie_companies, movie_info, movie_keyword, person_info, title
WHERE aka_title.season_nr = 63
  AND aka_title.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id;
