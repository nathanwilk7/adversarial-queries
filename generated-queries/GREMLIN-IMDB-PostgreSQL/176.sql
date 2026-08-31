SELECT count(*)
FROM company_name, complete_cast, info_type, keyword, movie_companies, movie_info, movie_keyword, person_info, title
WHERE company_name.name_pcode_sf = ''
  AND complete_cast.movie_id = title.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND person_info.info_type_id = info_type.id;
