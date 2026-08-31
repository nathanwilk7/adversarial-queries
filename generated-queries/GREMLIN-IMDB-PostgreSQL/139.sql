SELECT count(*)
FROM aka_title, company_type, info_type, keyword, movie_companies, movie_info, movie_keyword, movie_link, name, person_info, title
WHERE aka_title.season_nr = 63
  AND aka_title.movie_id = title.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.keyword_id = keyword.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id
  AND person_info.person_id = name.id;
