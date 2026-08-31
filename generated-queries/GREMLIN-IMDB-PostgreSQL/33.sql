SELECT count(*)
FROM aka_title, cast_info, company_type, info_type, movie_companies, movie_info, movie_keyword, movie_link, person_info, role_type, title
WHERE aka_title.episode_nr = 4315
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id;
