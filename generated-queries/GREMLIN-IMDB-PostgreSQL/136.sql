SELECT count(*)
FROM aka_title, company_name, complete_cast, info_type, movie_companies, movie_info, movie_keyword, name, person_info, title
WHERE aka_title.season_nr = 63
  AND aka_title.movie_id = title.id
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
